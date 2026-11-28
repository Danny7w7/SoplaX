"""Vistas previas cortas que se reproducen al pasar el cursor por una miniatura."""
import logging
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.files import File
from django.db import DatabaseError, router, transaction

from .models import Videos
from .video_durations import (
    VideoDurationError,
    mp4_input_options,
    read_local_video_duration,
    read_stored_video_duration,
    stored_video_source,
)


logger = logging.getLogger(__name__)
PREVIEW_QUEUE = "video_previews"
PREVIEW_TIMEOUT_SECONDS = 240
PREVIEW_JOB_TIMEOUT_SECONDS = 360
PREVIEW_HEIGHT = 360
PREVIEW_FPS = 24
CLIP_POSITIONS = (0.1, 0.3, 0.5, 0.7, 0.9)
CLIP_SECONDS = 2
SINGLE_CLIP_MAX_SECONDS = 10
SINGLE_CLIP_BELOW_SECONDS = 12


class VideoPreviewError(Exception):
    """No se pudo crear la vista previa. Los mensajes se pueden mostrar al equipo."""


def preview_clips(duration):
    """Devuelve los tramos (inicio, duración) en segundos que forman la vista previa."""
    if duration < SINGLE_CLIP_BELOW_SECONDS:
        return [(0, min(duration, SINGLE_CLIP_MAX_SECONDS))]
    latest_start = duration - CLIP_SECONDS
    return [(min(round(duration * position, 3), latest_start), CLIP_SECONDS) for position in CLIP_POSITIONS]


def preview_command(source, clips, output_path, *, remote=False):
    inputs = []
    filters = []
    for index, (start, length) in enumerate(clips):
        inputs += [*mp4_input_options(remote=remote), "-ss", str(start), "-t", str(length), "-i", str(source)]
        filters.append(
            f"[{index}:v:0]scale=-2:{PREVIEW_HEIGHT},fps={PREVIEW_FPS},setsar=1,format=yuv420p[v{index}]"
        )
    labels = "".join(f"[v{index}]" for index in range(len(clips)))
    filters.append(f"{labels}concat=n={len(clips)}:v=1:a=0[preview]")
    return [
        "ffmpeg", "-nostdin", "-v", "error", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[preview]", "-an", "-sn", "-dn",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-profile:v", "main",
        "-threads", "2", "-movflags", "+faststart", "-f", "mp4", str(output_path),
    ]


def build_preview(source, duration, output_path, *, remote=False):
    command = preview_command(source, preview_clips(duration), output_path, remote=remote)
    try:
        subprocess.run(
            command, check=True, capture_output=True, stdin=subprocess.DEVNULL,
            timeout=PREVIEW_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise VideoPreviewError("ffmpeg no está disponible para crear la vista previa.") from None
    except subprocess.TimeoutExpired:
        raise VideoPreviewError("Se agotó el tiempo para crear la vista previa.") from None
    except (OSError, subprocess.CalledProcessError):
        # La salida de FFmpeg puede incluir la URL firmada de S3. Solo se informa un mensaje fijo.
        raise VideoPreviewError("No se pudo crear la vista previa del MP4.") from None

    try:
        read_local_video_duration(output_path)
    except VideoDurationError:
        raise VideoPreviewError("La vista previa generada no es un MP4 válido.") from None


def discard_preview_file(name, *, using=None):
    """Borra un archivo de vista previa si ningún video lo usa. Devuelve False si falló."""
    if not name:
        return True
    using = using or router.db_for_write(Videos)
    storage = Videos._meta.get_field("preview").storage
    try:
        if Videos.objects.using(using).filter(preview=name).exists():
            return True
        storage.delete(name)
    except Exception:
        logger.exception("No se pudo eliminar la vista previa %s.", name)
        return False
    return True


def generate_video_preview(video_id, video_key):
    """Crea y guarda la vista previa del MP4 `video_key`. Devuelve su nombre, o None si el video cambió."""
    using = router.db_for_write(Videos)
    videos = Videos.objects.using(using)
    current = videos.filter(pk=video_id, video=video_key).values("duracion_segundos", "preview").first()
    if current is None:
        return None

    video_storage = Videos._meta.get_field("video").storage
    preview_field = Videos._meta.get_field("preview")
    duration = current["duracion_segundos"]
    try:
        if not duration:
            duration = read_stored_video_duration(video_storage, video_key)
        source, remote = stored_video_source(video_storage, video_key, expire=PREVIEW_TIMEOUT_SECONDS + 60)
    except VideoDurationError as error:
        raise VideoPreviewError(str(error)) from None

    name = preview_field.generate_filename(None, f"{uuid4().hex}.mp4")
    with TemporaryDirectory(prefix="soplax-preview-") as directory:
        output_path = Path(directory) / "preview.mp4"
        build_preview(source, duration, output_path, remote=remote)
        try:
            with output_path.open("rb") as output:
                stored = preview_field.storage.save(name, File(output), max_length=preview_field.max_length)
        except (BotoCoreError, ClientError, OSError):
            logger.exception("No se pudo guardar la vista previa del video %s.", video_id)
            raise VideoPreviewError("No se pudo guardar la vista previa.") from None

    changes = {"preview": stored}
    if not current["duracion_segundos"]:
        changes["duracion_segundos"] = duration
    try:
        updated = videos.filter(pk=video_id, video=video_key, preview=current["preview"]).update(**changes)
    except DatabaseError:
        discard_preview_file(stored, using=using)
        raise
    if not updated:
        # El video cambió mientras se creaba la vista previa: esta ya no le corresponde.
        discard_preview_file(stored, using=using)
        return None
    discard_preview_file(current["preview"], using=using)
    return stored


def _run_or_enqueue(video_id, video_key):
    # Se ejecuta tras confirmar el video: un fallo aquí nunca debe deshacer la carga ya guardada.
    try:
        if settings.DEVELOPMENT:
            generate_video_preview(video_id, video_key)
            return
        import django_rq

        django_rq.get_queue(PREVIEW_QUEUE, commit_mode="auto").enqueue(
            generate_video_preview,
            video_id,
            video_key,
            description=f"Vista previa del video {video_id}",
            job_timeout=PREVIEW_JOB_TIMEOUT_SECONDS,
            result_ttl=0,
            failure_ttl=7 * 24 * 3600,
        )
    except VideoPreviewError as error:
        logger.warning("No se pudo crear la vista previa del video %s: %s", video_id, error)
    except Exception:
        logger.exception("No se pudo programar la vista previa del video %s.", video_id)


def queue_video_preview(video, *, using=None):
    """Programa la vista previa del MP4 actual cuando se confirme la transacción en curso."""
    if not video.pk or not video.video:
        return
    video_id, video_key = video.pk, video.video.name
    transaction.on_commit(lambda: _run_or_enqueue(video_id, video_key), using=using)
