import logging
from contextlib import contextmanager
from uuid import uuid4

from django import forms
from PIL import Image

from .models import Videos


logger = logging.getLogger(__name__)
MIB = 1024 * 1024
VIDEO_LIMIT_MIB = 1000
THUMBNAIL_LIMIT_MIB = 10
THUMBNAIL_MAX_SIDE = 4096
THUMBNAIL_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


def upload_widget(accept, limit_mib):
    return forms.FileInput(
        attrs={
            "accept": accept,
            "data-max-bytes": limit_mib * MIB,
            "data-size-error": f"El archivo debe pesar como máximo {limit_mib} MiB.",
        }
    )


class VideoUploadForm(forms.ModelForm):
    video = forms.FileField(
        label="Archivo de video",
        help_text=f"MP4 · hasta {VIDEO_LIMIT_MIB} MiB",
        widget=upload_widget(".mp4,video/mp4", VIDEO_LIMIT_MIB),
    )
    miniatura = forms.FileField(
        label="Miniatura",
        help_text=f"JPG, PNG o WebP · hasta {THUMBNAIL_LIMIT_MIB} MiB · vista en 16:9",
        widget=upload_widget("image/jpeg,image/png,image/webp", THUMBNAIL_LIMIT_MIB),
    )

    class Meta:
        model = Videos
        fields = ("nombre", "descripcion", "video", "miniatura", "idioma", "categorias", "actores", "posturas")
        labels = {"nombre": "Título", "descripcion": "Descripción"}
        widgets = {
            "nombre": forms.TextInput(attrs={"autocomplete": "off"}),
            "descripcion": forms.Textarea(attrs={"class": "input", "rows": 5}),
            "idioma": forms.Select(attrs={"class": "input"}),
            "categorias": forms.SelectMultiple(attrs={"class": "input", "size": 4}),
            "actores": forms.SelectMultiple(attrs={"class": "input", "size": 4}),
            "posturas": forms.SelectMultiple(attrs={"class": "input", "size": 4}),
        }

    def clean_video(self):
        upload = self.cleaned_data["video"]
        if upload.size > VIDEO_LIMIT_MIB * MIB:
            raise forms.ValidationError(f"El video debe pesar como máximo {VIDEO_LIMIT_MIB} MiB.")
        header = upload.read(16)
        box_size = int.from_bytes(header[:4], "big")
        if (
            not upload.name.lower().endswith(".mp4")
            or len(header) != 16
            or header[4:8] != b"ftyp"
            or header[8:12] == b"qt  "
            or not 16 <= box_size <= upload.size
        ):
            raise forms.ValidationError("Selecciona un archivo de video MP4 válido.")
        upload.seek(0)
        upload.name = f"{uuid4().hex}.mp4"
        upload.content_type = "video/mp4"
        return upload

    def clean_miniatura(self):
        upload = self.cleaned_data["miniatura"]
        if upload.size > THUMBNAIL_LIMIT_MIB * MIB:
            raise forms.ValidationError(f"La miniatura debe pesar como máximo {THUMBNAIL_LIMIT_MIB} MiB.")
        try:
            with Image.open(upload, formats=tuple(THUMBNAIL_FORMATS)) as image:
                if max(image.size) > THUMBNAIL_MAX_SIDE:
                    raise forms.ValidationError(f"Usa una imagen de hasta {THUMBNAIL_MAX_SIDE} píxeles por lado.")
                if getattr(image, "is_animated", False):
                    raise forms.ValidationError("Selecciona una imagen estática para la miniatura.")
                image.load()
                extension, content_type = THUMBNAIL_FORMATS[image.format]
        except (Image.DecompressionBombError, OSError, SyntaxError, ValueError) as error:
            raise forms.ValidationError("Selecciona una imagen JPG, PNG o WebP válida.") from error
        upload.seek(0)
        upload.name = f"{uuid4().hex}{extension}"
        upload.content_type = content_type
        return upload


@contextmanager
def store_video_uploads(video):
    saved = []
    try:
        for asset in (video.video, video.miniatura):
            upload = asset.file
            name = asset.field.generate_filename(video, upload.name)
            if asset.storage.exists(name):
                raise OSError("La clave generada para la carga ya existe.")
            # Track the key before writing in case storage fails after receiving the file.
            saved.append((asset.storage, name))
            stored_name = asset.storage.save(name, upload, max_length=asset.field.max_length)
            saved[-1] = (asset.storage, stored_name)
            setattr(video, asset.field.attname, stored_name)
        yield
    except Exception:
        for storage, name in reversed(saved):
            try:
                storage.delete(name)
            except Exception:
                logger.exception("No se pudo eliminar el archivo %s de una carga incompleta.", name)
        raise
