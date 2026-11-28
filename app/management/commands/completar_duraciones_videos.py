from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, router, transaction

from app.models import Videos
from app.video_durations import VideoDurationError, read_stored_video_duration


def prepare_durations(storage, candidates):
    readings = {}
    changes = []
    failures = []
    for video_id, key in candidates:
        if key not in readings:
            try:
                readings[key] = (read_stored_video_duration(storage, key), None)
            except VideoDurationError as error:
                readings[key] = (None, str(error))
        duration, error = readings[key]
        if error is None:
            changes.append((video_id, key, duration))
        else:
            failures.append((video_id, error))
    return changes, failures


def apply_durations(videos, changes, *, using):
    try:
        with transaction.atomic(using=using):
            for video_id, key, duration in changes:
                updated = videos.filter(
                    pk=video_id,
                    video=key,
                    duracion_segundos__isnull=True,
                ).update(duracion_segundos=duration)
                if updated != 1:
                    raise CommandError(
                        f"El archivo o la duración del video {video_id} cambió durante la preparación. "
                        "Se revirtieron los cambios. Ejecuta otra simulación."
                    )
    except DatabaseError as error:
        raise CommandError("Un error de base de datos revirtió el lote de duraciones.") from error


class Command(BaseCommand):
    help = "Completa las duraciones pendientes del catálogo de SoplaX. Simula por defecto."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Muestra el plan de solo lectura.")
        mode.add_argument("--aplicar", action="store_true", help="Guarda las duraciones calculadas.")

    def handle(self, *args, **options):
        apply = options["aplicar"]
        if apply and options["dry_run"]:
            raise CommandError("Elige --dry-run o --aplicar.")

        using = router.db_for_write(Videos)
        videos = Videos.objects.using(using)
        with_file = videos.exclude(video="")
        try:
            candidates = list(
                with_file.filter(duracion_segundos__isnull=True).order_by("pk").values_list("pk", "video")
            )
            existing = with_file.filter(duracion_segundos__isnull=False).count()
            without_file = videos.filter(video="").count()
        except DatabaseError as error:
            raise CommandError("Comprueba la conexión y las migraciones del catálogo de SoplaX.") from error

        storage = Videos._meta.get_field("video").storage
        changes, failures = prepare_durations(storage, candidates)
        for video_id, _, duration in changes:
            self.stdout.write(f"Video {video_id}: duración pendiente → {duration} s.")
        for video_id, error in failures:
            self.stderr.write(f"Video {video_id}: {error}")

        if failures:
            result = f"Plan incompleto: {len(changes)} duraciones calculadas"
        elif apply:
            if changes:
                apply_durations(videos, changes, using=using)
            result = f"Aplicado: {len(changes)} duraciones completadas"
        else:
            result = f"Simulación: {len(changes)} duraciones por completar"

        self.stdout.write(
            f"{result}. Duraciones ya registradas: {existing}. Videos sin archivo: {without_file}. "
            f"Errores de lectura: {len(failures)}. Altas: 0. Bajas: 0."
        )
        if failures:
            raise CommandError("El lote se canceló. Corrige los errores de lectura y repite la simulación.")
