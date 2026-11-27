from dataclasses import dataclass
from hashlib import sha256

from botocore.exceptions import BotoCoreError, ClientError
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, router, transaction
from django.db.models import Q
from PIL import features

from app.models import Videos, miniatura_directory
from app.video_uploads import thumbnail_webp_content


@dataclass(frozen=True)
class Relocation:
    source: str
    destination: str
    premium: bool
    video_ids: tuple[int, ...]
    original_size: int
    content: bytes
    destination_exists: bool


def prepare_relocations(storage, *, using):
    grouped = {}
    empty = 0
    expected = {}
    for video_id, premium, source in (
        Videos.objects.using(using).order_by("pk").values_list("pk", "es_premium", "miniatura").iterator()
    ):
        if not source:
            empty += 1
            continue
        expected[video_id] = source
        grouped.setdefault((source, premium), []).append(video_id)

    source_content = {}
    relocations = []
    for (source, premium), video_ids in grouped.items():
        if source not in source_content:
            try:
                with storage.open(source, "rb") as thumbnail:
                    raw = thumbnail.read()
                source_content[source] = (thumbnail_webp_content(raw), len(raw))
            except (OSError, ValueError, BotoCoreError, ClientError) as error:
                raise CommandError(f"No se pudo preparar la miniatura {source!r}.") from error

        content, original_size = source_content[source]
        digest = sha256(content).hexdigest()
        destination = f"{miniatura_directory(premium)}/{digest}.webp"
        relocations.append(
            Relocation(
                source=source,
                destination=destination,
                premium=premium,
                video_ids=tuple(video_ids),
                original_size=original_size,
                content=content,
                destination_exists=False,
            )
        )

    exists_by_destination = {}
    try:
        for relocation in relocations:
            if relocation.destination not in exists_by_destination:
                exists_by_destination[relocation.destination] = storage.exists(relocation.destination)
    except (OSError, BotoCoreError, ClientError) as error:
        raise CommandError("No se pudo consultar el estado de las miniaturas en S3.") from error

    relocations = [
        Relocation(
            source=item.source,
            destination=item.destination,
            premium=item.premium,
            video_ids=item.video_ids,
            original_size=item.original_size,
            content=item.content,
            destination_exists=exists_by_destination[item.destination],
        )
        for item in relocations
    ]
    return relocations, empty, expected


def apply_relocations(storage, relocations, expected, *, using):
    expected_destinations = {
        video_id: relocation.destination
        for relocation in relocations
        for video_id in relocation.video_ids
    }
    changed = {
        video_id: destination
        for video_id, destination in expected_destinations.items()
        if expected[video_id] != destination
    }
    created = []
    try:
        with transaction.atomic(using=using):
            videos = Videos.objects.using(using).filter(pk__in=expected)
            current = dict(videos.select_for_update().order_by("pk").values_list("pk", "miniatura"))
            if current != expected:
                raise CommandError("El catálogo cambió durante la preparación. Ejecuta otra simulación.")

            unique_destinations = {}
            for relocation in relocations:
                if any(expected[video_id] != relocation.destination for video_id in relocation.video_ids):
                    unique_destinations.setdefault(relocation.destination, relocation.content)

            for destination, content_bytes in unique_destinations.items():
                if storage.exists(destination):
                    try:
                        with storage.open(destination, "rb") as existing:
                            matches = existing.read() == content_bytes
                    except (OSError, BotoCoreError, ClientError) as error:
                        raise CommandError(f"No se pudo verificar el destino {destination!r}.") from error
                    if not matches:
                        raise CommandError(f"El destino {destination!r} ya existe con otro contenido.")
                    continue

                content = ContentFile(content_bytes, name=destination.rsplit("/", 1)[-1])
                content.content_type = "image/webp"
                stored_name = storage.save(destination, content)
                created.append(stored_name)
                if stored_name != destination:
                    raise CommandError(f"El destino {destination!r} cambió durante la escritura a {stored_name!r}.")

            for relocation in relocations:
                if relocation.source == relocation.destination:
                    continue
                updated = videos.filter(
                    pk__in=relocation.video_ids,
                    miniatura=relocation.source,
                ).update(miniatura=relocation.destination)
                if updated != len(relocation.video_ids):
                    raise CommandError("No se pudieron actualizar todas las referencias de una miniatura.")
    except Exception as error:
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
        raise CommandError(f"Reubicación revertida por un error de tipo {type(error).__name__}.") from error
    return changed


def remove_unreferenced_sources(storage, relocations, *, using):
    destinations = {item.destination for item in relocations}
    sources = {item.source for item in relocations if item.source not in destinations}
    deleted = []
    retained = []
    failed = []
    for source in sorted(sources):
        try:
            referenced = Videos.objects.using(using).filter(Q(video=source) | Q(miniatura=source)).exists()
        except DatabaseError:
            retained.append(source)
            continue
        if referenced:
            retained.append(source)
            continue
        try:
            storage.delete(source)
            deleted.append(source)
        except (OSError, BotoCoreError, ClientError):
            failed.append(source)
    return deleted, retained, failed


class Command(BaseCommand):
    help = "Reubica miniaturas como WebP en carpetas Premium y NoPremium. Simula por defecto."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Muestra el plan sin escribir en S3 ni en la base.")
        mode.add_argument("--aplicar", action="store_true", help="Reubica miniaturas y actualiza sus referencias.")

    def handle(self, *args, **options):
        if not features.check("webp"):
            raise CommandError("Pillow debe tener soporte para WebP.")

        storage = Videos._meta.get_field("miniatura").storage
        using = router.db_for_write(Videos)
        apply = options["aplicar"]
        try:
            relocations, empty, expected = prepare_relocations(storage, using=using)
            if apply:
                changed = apply_relocations(storage, relocations, expected, using=using)
                deleted, retained, failed = remove_unreferenced_sources(storage, relocations, using=using)
            else:
                changed = {
                    video_id: item.destination
                    for item in relocations
                    for video_id in item.video_ids
                    if expected[video_id] != item.destination
                }
                old_sources = {item.source for item in relocations}
                destinations = {item.destination for item in relocations}
                candidates = old_sources - destinations
                referenced_by_video = set(
                    Videos.objects.using(using)
                    .filter(video__in=candidates)
                    .values_list("video", flat=True)
                )
                deleted = sorted(candidates - referenced_by_video)
                retained = sorted(referenced_by_video)
                failed = []
        except DatabaseError as error:
            raise CommandError("Comprueba la conexión y el estado del catálogo de SoplaX.") from error
        except (OSError, BotoCoreError, ClientError) as error:
            raise CommandError("No se pudo consultar o actualizar el almacenamiento de miniaturas.") from error

        for item in relocations:
            status = "sin cambio" if item.source == item.destination else (
                "reutiliza destino" if item.destination_exists else "crea destino"
            )
            ids = ", ".join(map(str, item.video_ids))
            self.stdout.write(
                f"Videos {ids}: {item.source} → {item.destination} "
                f"({item.original_size} → {len(item.content)} bytes; {status})."
            )

        verb = "Aplicado" if apply else "Simulación"
        self.stdout.write(
            f"{verb}: {len(changed)} referencias por reubicar, {empty} videos sin miniatura. "
            f"Fuentes obsoletas: {len(deleted)} por retirar, {len(retained)} por conservar por referencia."
        )
        for source in deleted:
            self.stdout.write(f"S3 {'retiró' if apply else 'retiraría'}: {source}")
        for source in retained:
            self.stdout.write(f"S3 conserva: {source} (todavía tiene referencias).")
        if apply:
            self.stdout.write(f"S3: {len(deleted)} fuentes retiradas, {len(retained)} conservadas.")
            if failed:
                self.stderr.write("No se pudieron retirar estas fuentes de S3: " + ", ".join(failed))
        else:
            self.stdout.write("La simulación no escribió en S3 ni modificó referencias.")
