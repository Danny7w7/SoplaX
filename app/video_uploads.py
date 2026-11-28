import logging
from io import BytesIO
from contextlib import contextmanager
from uuid import uuid4

from django import forms
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps

from .models import Videos
from .video_durations import VideoDurationError, read_uploaded_video_duration


logger = logging.getLogger(__name__)
MIB = 1024 * 1024
VIDEO_LIMIT_MIB = 1000
THUMBNAIL_LIMIT_MIB = 10
THUMBNAIL_MAX_SIDE = 4096
THUMBNAIL_FORMAT = "WEBP"
THUMBNAIL_SIZE = (960, 540)
WEBP_QUALITY = 82


def upload_widget(accept, limit_mib):
    return forms.FileInput(
        attrs={
            "accept": accept,
            "data-max-bytes": limit_mib * MIB,
            "data-size-error": f"El archivo debe pesar como máximo {limit_mib} MiB.",
        }
    )


class VideoFileForm(forms.ModelForm):
    class Meta:
        model = Videos
        fields = "__all__"

    def clean_video(self):
        video = self.cleaned_data["video"]
        if isinstance(video, UploadedFile):
            video = validate_video_upload(video)
            try:
                self.instance.duracion_segundos = read_uploaded_video_duration(video)
            except VideoDurationError as error:
                raise forms.ValidationError(str(error), code="video_duration") from error
        return video

    def video_update_fields(self):
        fields = {field.name for field in Videos._meta.concrete_fields if field.name in self.changed_data}
        if "video" in fields:
            fields.add("duracion_segundos")
        return fields


class VideoUploadForm(VideoFileForm):
    video = forms.FileField(
        label="Archivo de video",
        help_text=f"MP4 · hasta {VIDEO_LIMIT_MIB} MiB",
        widget=upload_widget(".mp4,video/mp4", VIDEO_LIMIT_MIB),
    )
    miniatura = forms.FileField(
        label="Miniatura",
        help_text=f"WebP · hasta {THUMBNAIL_LIMIT_MIB} MiB · vista en 16:9",
        widget=upload_widget("image/webp,.webp", THUMBNAIL_LIMIT_MIB),
    )

    class Meta:
        model = Videos
        fields = (
            "nombre",
            "descripcion",
            "es_premium",
            "video",
            "miniatura",
            "idioma",
            "categorias",
            "actores",
            "posturas",
        )
        labels = {"nombre": "Título", "descripcion": "Descripción", "es_premium": "Contenido premium"}
        help_texts = {
            "es_premium": "Las miniaturas se guardan en una carpeta separada según este valor."
        }
        widgets = {
            "nombre": forms.TextInput(attrs={"autocomplete": "off"}),
            "descripcion": forms.Textarea(attrs={"class": "input", "rows": 5}),
            "idioma": forms.Select(attrs={"class": "input"}),
            "categorias": forms.SelectMultiple(attrs={"class": "input", "size": 4}),
            "actores": forms.SelectMultiple(attrs={"class": "input", "size": 4}),
            "posturas": forms.SelectMultiple(attrs={"class": "input", "size": 4}),
        }

    def clean_miniatura(self):
        return validate_thumbnail_upload(self.cleaned_data["miniatura"])


class VideoManagementForm(VideoUploadForm):
    """Edit video metadata and optionally replace either stored asset."""

    video = forms.FileField(
        label="Archivo de video",
        required=False,
        help_text=f"MP4 · hasta {VIDEO_LIMIT_MIB} MiB · Déjalo vacío para conservar el actual.",
        widget=upload_widget(".mp4,video/mp4", VIDEO_LIMIT_MIB),
    )
    miniatura = forms.FileField(
        label="Miniatura",
        required=False,
        help_text=f"WebP · hasta {THUMBNAIL_LIMIT_MIB} MiB · Déjala vacía para conservar la actual.",
        widget=upload_widget("image/webp,.webp", THUMBNAIL_LIMIT_MIB),
    )

    def clean_miniatura(self):
        upload = self.files.get(self.add_prefix("miniatura"))
        return validate_thumbnail_upload(upload) if upload else self.instance.miniatura


def validate_video_upload(upload):
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


def validate_thumbnail_upload(upload):
    if upload.size > THUMBNAIL_LIMIT_MIB * MIB:
        raise forms.ValidationError(f"La miniatura debe pesar como máximo {THUMBNAIL_LIMIT_MIB} MiB.")
    try:
        with Image.open(upload, formats=(THUMBNAIL_FORMAT,)) as image:
            if max(image.size) > THUMBNAIL_MAX_SIDE:
                raise forms.ValidationError(f"Usa una imagen de hasta {THUMBNAIL_MAX_SIDE} píxeles por lado.")
            if getattr(image, "is_animated", False):
                raise forms.ValidationError("Selecciona una imagen estática para la miniatura.")
            image.load()
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError) as error:
        raise forms.ValidationError("Selecciona una miniatura WebP válida.") from error
    upload.seek(0)
    upload.name = f"{uuid4().hex}.webp"
    upload.content_type = "image/webp"
    return upload


def thumbnail_webp_content(content):
    """Return valid, static WebP bytes, converting legacy image formats as needed."""
    try:
        with Image.open(BytesIO(content)) as image:
            if getattr(image, "is_animated", False):
                raise ValueError("La miniatura es animada.")
            if image.format == THUMBNAIL_FORMAT:
                image.load()
                return content

            mode = "RGBA" if image.has_transparency_data else "RGB"
            with ImageOps.exif_transpose(image) as oriented, oriented.convert(mode) as thumbnail:
                thumbnail.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                with BytesIO() as output:
                    thumbnail.save(output, THUMBNAIL_FORMAT, quality=WEBP_QUALITY, method=6)
                    return output.getvalue()
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError) as error:
        raise ValueError("No se pudo leer la miniatura como una imagen válida.") from error


@contextmanager
def store_video_uploads(video, fields=("video", "miniatura")):
    saved = []
    try:
        for field_name in fields:
            asset = getattr(video, field_name)
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
