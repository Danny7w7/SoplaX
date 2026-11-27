from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from PIL import Image, ImageOps, features

from app.models import Videos


WEBP_DIRECTORY = "upload/photos/webp"
THUMBNAIL_SIZE = (960, 540)
WEBP_QUALITY = 82


@dataclass(frozen=True)
class Conversion:
    source: str
    video_ids: tuple[int, ...]
    original_size: int
    content: bytes


def prepare_conversions(storage):
    videos_by_thumbnail = {}
    skipped = 0
    rows = Videos.objects.order_by("pk").values_list("pk", "miniatura")
    for video_id, source in rows.iterator():
        if not source or source.lower().endswith(".webp"):
            skipped += 1
            continue
        videos_by_thumbnail.setdefault(source, []).append(video_id)

    conversions = []
    for source, video_ids in videos_by_thumbnail.items():
        try:
            with storage.open(source, "rb") as file, Image.open(file) as image, BytesIO() as output:
                if getattr(image, "is_animated", False):
                    raise CommandError(f"La miniatura {source!r} es animada. Revisa ese archivo antes de convertirlo.")
                mode = "RGBA" if image.has_transparency_data else "RGB"
                with ImageOps.exif_transpose(image) as oriented, oriented.convert(mode) as thumbnail:
                    thumbnail.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                    thumbnail.save(output, "WEBP", quality=WEBP_QUALITY, method=6)
                conversions.append(
                    Conversion(
                        source=source,
                        video_ids=tuple(video_ids),
                        original_size=file.size,
                        content=output.getvalue(),
                    )
                )
        except (OSError, ValueError, Image.DecompressionBombError, BotoCoreError, ClientError) as error:
            raise CommandError(f"No se pudo convertir la miniatura {source!r}.") from error

    return conversions, skipped


def apply_conversions(storage, conversions):
    expected = {video_id: item.source for item in conversions for video_id in item.video_ids}
    with transaction.atomic():
        videos = Videos.objects.filter(pk__in=expected)
        current = dict(videos.select_for_update().order_by("pk").values_list("pk", "miniatura"))
        if current != expected:
            raise CommandError("El catálogo cambió durante la preparación. Ejecuta otra simulación.")

        created = []
        try:
            for item in conversions:
                destination = f"{WEBP_DIRECTORY}/{uuid4().hex}.webp"
                if storage.exists(destination):
                    raise CommandError(f"El destino {destination!r} ya existe.")
                # Cada conversión usa una clave nueva para poder retirar solo los archivos de este intento.
                created.append(destination)
                with ContentFile(item.content) as content:
                    content.content_type = "image/webp"
                    created[-1] = storage.save(destination, content)
            for item, destination in zip(conversions, created, strict=True):
                updated = videos.filter(pk__in=item.video_ids).update(miniatura=destination)
                if updated != len(item.video_ids):
                    raise CommandError("No se pudieron actualizar todas las referencias de una miniatura.")
        except (Exception, KeyboardInterrupt) as error:
            pending = []
            for destination in created:
                try:
                    storage.delete(destination)
                except (OSError, BotoCoreError, ClientError):
                    pending.append(destination)
            if pending:
                raise CommandError(
                    f"Se revirtieron las referencias. Quedaron archivos nuevos sin referencias: {', '.join(pending)}."
                ) from error
            if isinstance(error, CommandError):
                raise
            raise CommandError(f"Conversión revertida por un error de tipo {type(error).__name__}.") from error
    return created


class Command(BaseCommand):
    help = "Convierte las miniaturas existentes a WebP y conserva los originales. Simula por defecto."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Muestra el plan de conversión sin escrituras.")
        mode.add_argument("--aplicar", action="store_true", help="Guarda las WebP y cambia las referencias.")

    def handle(self, *args, **options):
        if not features.check("webp"):
            raise CommandError("Pillow debe tener soporte para WebP.")

        storage = Videos._meta.get_field("miniatura").storage
        apply = options["aplicar"]
        if apply and options["dry_run"]:
            raise CommandError("Elige un solo modo: --dry-run o --aplicar.")
        try:
            conversions, skipped = prepare_conversions(storage)
            if apply and conversions:
                destinations = apply_conversions(storage, conversions)
            else:
                destinations = [f"{WEBP_DIRECTORY}/<clave-nueva>.webp"] * len(conversions)
        except DatabaseError as error:
            raise CommandError("Comprueba la conexión y el estado de las referencias en la base de SoplaX.") from error

        for item, destination in zip(conversions, destinations, strict=True):
            ids = ", ".join(map(str, item.video_ids))
            self.stdout.write(
                f"Videos {ids}: {item.source} → {destination} "
                f"({item.original_size} → {len(item.content)} bytes)."
            )

        video_count = sum(len(item.video_ids) for item in conversions)
        before = sum(item.original_size for item in conversions)
        after = sum(len(item.content) for item in conversions)
        summary = "Aplicado" if apply else "Simulación"
        self.stdout.write(
            f"{summary}: {len(conversions)} WebP nuevas, {video_count} referencias, {skipped} sin cambios. "
            f"{before} → {after} bytes. Archivos originales borrados: 0."
        )
