import json
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadedfile import TemporaryUploadedFile
from storages.backends.s3 import S3Storage


PROBE_TIMEOUT_SECONDS = 30
MAX_DURATION_SECONDS = 2_147_483_647


class VideoDurationError(Exception):
    """A duration could not be read. Messages are safe to show to operators."""


def _probe_duration(source, *, remote=False):
    if remote:
        source_options = [
            "-protocol_whitelist", "https,tls,tcp",
            "-tls_verify", "1",
            "-seekable", "1",
            "-rw_timeout", "5000000",
        ]
    else:
        source_options = ["-protocol_whitelist", "file"]
    command = [
        "ffprobe", "-v", "error", *source_options,
        "-f", "mov", "-enable_drefs", "0", "-use_absolute_path", "0",
        "-select_streams", "V", "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", "-i", str(source),
    ]

    try:
        result = subprocess.run(
            command, check=True, capture_output=True, stdin=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise VideoDurationError("ffprobe no está disponible para calcular la duración.") from None
    except subprocess.TimeoutExpired:
        raise VideoDurationError("Se agotó el tiempo para calcular la duración del MP4.") from None
    except (OSError, subprocess.CalledProcessError):
        # Process errors may contain a signed S3 URL. Report only a stable message.
        raise VideoDurationError("No se pudo leer el archivo MP4.") from None

    try:
        metadata = json.loads(result.stdout)
        duration = Decimal(metadata["format"]["duration"])
        streams = metadata["streams"]
    except (ValueError, InvalidOperation, KeyError, TypeError):
        raise VideoDurationError("No se pudo leer la duración del archivo MP4.") from None

    if not streams or not duration.is_finite() or not 0 < duration <= MAX_DURATION_SECONDS:
        raise VideoDurationError("El archivo MP4 debe tener una pista de video y una duración válida.")

    return max(1, int(duration))


def read_uploaded_video_duration(upload):
    try:
        upload.seek(0)
        if isinstance(upload, TemporaryUploadedFile):
            return _probe_duration(upload.temporary_file_path())

        with TemporaryDirectory(prefix="soplax-video-") as directory:
            path = Path(directory) / "video.mp4"
            with path.open("wb") as file:
                for chunk in upload.chunks():
                    file.write(chunk)
            return _probe_duration(path)
    except OSError:
        raise VideoDurationError("No se pudo leer el archivo de video cargado.") from None
    finally:
        upload.seek(0)


def read_stored_video_duration(storage, name):
    remote = isinstance(storage, S3Storage)
    try:
        if remote:
            source = storage.url(name, expire=2 * PROBE_TIMEOUT_SECONDS, http_method="GET")
            if urlsplit(source).scheme != "https":
                raise VideoDurationError("La URL del video en S3 debe usar HTTPS.")
        else:
            source = storage.path(name)
    except (BotoCoreError, ClientError, NotImplementedError, OSError, SuspiciousOperation, ValueError):
        raise VideoDurationError("No se pudo acceder al archivo de video guardado.") from None

    return _probe_duration(source, remote=remote)
