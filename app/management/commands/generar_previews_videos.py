from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, router

from app.models import Videos
from app.video_durations import VideoDurationError, read_stored_video_duration
from app.video_previews import VideoPreviewError, generate_video_preview, preview_clips


def positive_int(value):
    number = int(value)
    if number < 1:
        raise ValueError
    return number


class Command(BaseCommand):
    help = "Crea las vistas previas pendientes del catálogo de SoplaX. Simula por defecto."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Muestra el plan de solo lectura.")
        mode.add_argument("--aplicar", action="store_true", help="Crea y guarda las vistas previas.")
        parser.add_argument("--limite", type=positive_int, help="Procesa como máximo esta cantidad de videos.")

    def handle(self, *args, **options):
        apply = options["aplicar"]
        using = router.db_for_write(Videos)
        videos = Videos.objects.using(using)
        with_file = videos.exclude(video="")
        try:
            pending = with_file.filter(preview="").order_by("pk").values_list("pk", "video", "duracion_segundos")
            candidates = list(pending[: options["limite"]] if options["limite"] else pending)
            existing = with_file.exclude(preview="").count()
            without_file = videos.filter(video="").count()
        except DatabaseError as error:
            raise CommandError("Comprueba la conexión y las migraciones del catálogo de SoplaX.") from error

        storage = Videos._meta.get_field("video").storage
        done = 0
        skipped = 0
        failures = []
        for video_id, key, duration in candidates:
            try:
                if apply:
                    name = generate_video_preview(video_id, key)
                    if name is None:
                        skipped += 1
                        self.stdout.write(f"Video {video_id}: cambió durante el proceso; se omitió.")
                        continue
                    self.stdout.write(f"Video {video_id}: vista previa creada → {name}.")
                else:
                    duration = duration or read_stored_video_duration(storage, key)
                    clips = preview_clips(duration)
                    seconds = sum(length for _, length in clips)
                    self.stdout.write(
                        f"Video {video_id}: vista previa pendiente → {len(clips)} tramos, {seconds:g} s "
                        f"(video de {duration} s)."
                    )
                done += 1
            except (VideoDurationError, VideoPreviewError, DatabaseError) as error:
                failures.append(video_id)
                self.stderr.write(f"Video {video_id}: {error}")

        if apply:
            result = f"Aplicado: {done} vistas previas creadas. Omitidas por cambios: {skipped}"
        else:
            result = f"Simulación: {done} vistas previas por crear"
        self.stdout.write(
            f"{result}. Vistas previas ya registradas: {existing}. Videos sin archivo: {without_file}. "
            f"Errores: {len(failures)}."
        )
        if failures:
            raise CommandError("Algunos videos fallaron. Revisa los errores y repite la simulación.")
