import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction

from app.models import Videos, miniatura_directory
from app.video_uploads import MIB, THUMBNAIL_LIMIT_MIB


HASH_WEBP = re.compile(r"[a-f0-9]{64}\.webp")
NAMED_WEBP = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.webp")


@dataclass(frozen=True)
class Reference:
    video: str
    premium: bool
    origins: tuple[str, ...]
    webp: str
    destination: str

    @property
    def digest(self):
        return self.webp.rsplit("/", 1)[-1].removesuffix(".webp")


@dataclass(frozen=True)
class Change:
    video_id: int
    reference: Reference
    source: str
    destination: str


def is_file_key(value):
    return (
        isinstance(value, str)
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and not any(ord(char) < 32 for char in value)
    )


def read_manifest(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CommandError("No se pudo leer el mapa de miniaturas.") from error
    if not isinstance(data, list) or not data:
        raise CommandError("El mapa debe contener una lista de miniaturas.")

    entries = {}
    destinations = set()
    max_length = Videos._meta.get_field("miniatura").max_length
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict) or item.keys() != {"video", "es_premium", "origenes", "webp_actual", "destino"}:
            raise CommandError(f"La entrada {index} está incompleta.")
        video, premium = item["video"], item["es_premium"]
        origins, webp, destination = item["origenes"], item["webp_actual"], item["destino"]
        if not is_file_key(video) or not isinstance(premium, bool):
            raise CommandError(f"La entrada {index} tiene un video o segmento inválido.")
        if not isinstance(origins, list) or not origins or not all(map(is_file_key, origins)):
            raise CommandError(f"La entrada {index} tiene claves anteriores inválidas.")
        prefix = miniatura_directory(premium) + "/"
        if not isinstance(webp, str) or not webp.startswith(prefix) or not HASH_WEBP.fullmatch(webp[len(prefix):]):
            raise CommandError(f"La entrada {index} necesita una clave WebP con hash del segmento indicado.")
        if (
            not isinstance(destination, str)
            or not destination.startswith(prefix)
            or not NAMED_WEBP.fullmatch(destination[len(prefix):])
            or HASH_WEBP.fullmatch(destination[len(prefix):])
            or len(destination) > max_length
        ):
            raise CommandError(f"La entrada {index} necesita un nombre WebP válido del segmento indicado.")
        if video in entries or destination in destinations:
            raise CommandError(f"La entrada {index} repite un video o un destino.")
        entries[video] = Reference(video, premium, tuple(origins), webp, destination)
        destinations.add(destination)

    return entries


def prepare_changes(videos, entries, *, use_existing_webp):
    seen = set()
    changes = []
    for video_id, video, premium, current in videos.values_list("pk", "video", "es_premium", "miniatura"):
        if video in seen:
            raise CommandError(f"La clave del video {video_id} corresponde a más de un registro.")
        seen.add(video)
        reference = entries[video]
        if premium != reference.premium:
            raise CommandError(f"El segmento del video {video_id} no coincide con el mapa.")
        if current == reference.destination:
            continue
        if current != reference.webp and current not in reference.origins:
            raise CommandError(f"El video {video_id} tiene una miniatura inesperada.")
        destination = reference.webp if use_existing_webp else reference.destination
        if current != destination:
            changes.append(Change(video_id, reference, current, destination))

    missing = entries.keys() - seen
    if missing:
        raise CommandError(f"Faltan {len(missing)} videos del mapa en la base de SoplaX.")
    return changes


def read_verified_webp(storage, key, reference, *, allow_missing=False):
    limit = THUMBNAIL_LIMIT_MIB * MIB
    try:
        with storage.open(key, "rb") as file:
            content = file.read(limit + 1)
    except FileNotFoundError as error:
        if allow_missing:
            return None
        raise CommandError(f"La WebP {ascii(key)} todavía no está publicada.") from error
    if len(content) > limit or sha256(content).hexdigest() != reference.digest:
        raise CommandError(f"El contenido de {ascii(key)} no coincide con la WebP esperada.")
    return content


def prepare_copies(storage, entries, *, publication):
    copies = []
    for reference in entries.values():
        content = read_verified_webp(storage, reference.destination, reference, allow_missing=publication)
        if content is None:
            copies.append((reference, read_verified_webp(storage, reference.webp, reference)))
    return copies


def publish_webp(storage, reference, content):
    key = storage._normalize_name(reference.destination)
    try:
        storage.connection.meta.client.put_object(
            Bucket=storage.bucket_name,
            Key=key,
            Body=content,
            ContentType="image/webp",
            IfNoneMatch="*",
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {"412", "PreconditionFailed"}:
            raise
        read_verified_webp(storage, reference.destination, reference)
        return False
    return True


def is_compose_catalog(database):
    return (
        not settings.DEVELOPMENT
        and settings.SETTINGS_MODULE == "project.settings_docker"
        and database.vendor == "postgresql"
        and database.settings_dict["HOST"] == "postgres"
    )


class Command(BaseCommand):
    help = "Repara las referencias de miniaturas de un mapa privado y publica nombres en el PostgreSQL de Compose."

    def add_arguments(self, parser):
        parser.add_argument("mapa", type=Path, help="Archivo JSON con las WebP y sus referencias verificadas.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Muestra el plan de solo lectura. Es el modo predeterminado.")
        mode.add_argument("--aplicar", action="store_true", help="Aplica el plan al catálogo de SoplaX.")
        parser.add_argument(
            "--usar-webp-existentes",
            action="store_true",
            help="En SQLite local, restaura las claves WebP con hash del mapa mientras se publican los nombres.",
        )

    def handle(self, *args, **options):
        using = DEFAULT_DB_ALIAS
        database = connections[using]
        publication = is_compose_catalog(database)
        if not publication and not (settings.DEVELOPMENT and database.vendor == "sqlite"):
            raise CommandError("Usa el SQLite de desarrollo o el PostgreSQL de Compose asignado a SoplaX.")

        use_existing_webp = options["usar_webp_existentes"]
        if publication and use_existing_webp:
            raise CommandError("--usar-webp-existentes está reservado para SQLite en desarrollo.")
        entries = read_manifest(options["mapa"])
        videos = Videos.objects.using(using).filter(video__in=entries).order_by("pk")
        storage = Videos._meta.get_field("miniatura").storage
        applying = options["aplicar"]
        published = []
        try:
            changes = prepare_changes(videos, entries, use_existing_webp=use_existing_webp)
            copies = [] if use_existing_webp else prepare_copies(storage, entries, publication=publication)
            if applying:
                with transaction.atomic(using=using):
                    locked = prepare_changes(videos.select_for_update(), entries, use_existing_webp=use_existing_webp)
                    if locked != changes:
                        raise CommandError("El catálogo cambió durante la preparación. Ejecuta otra simulación.")

                    for reference, content in copies:
                        if publish_webp(storage, reference, content):
                            published.append(reference.destination)

                    for change in changes:
                        updated = videos.filter(
                            pk=change.video_id,
                            video=change.reference.video,
                            es_premium=change.reference.premium,
                            miniatura=change.source,
                        ).update(miniatura=change.destination)
                        if updated != 1:
                            raise CommandError(f"No se pudo actualizar la miniatura del video {change.video_id}.")
        except (DatabaseError, OSError, BotoCoreError, ClientError, CommandError) as error:
            if published:
                self.stderr.write(f"Quedaron {len(published)} copias WebP disponibles para el siguiente intento.")
            if isinstance(error, CommandError):
                raise
            raise CommandError(f"No se pudo completar el plan ({type(error).__name__}).") from error

        for change in changes:
            self.stdout.write(f"Video {change.video_id}: {ascii(change.source)} -> {ascii(change.destination)}")
        for name in published if applying else (reference.destination for reference, _ in copies):
            self.stdout.write(f"S3 {'creó' if applying else 'crearía'} {ascii(name)}")
        resolved = len(entries) - len(changes)
        if applying:
            self.stdout.write(f"Aplicado: {len(changes)} referencias actualizadas, {resolved} correctas, {len(published)} WebP creadas.")
        else:
            self.stdout.write(f"Simulación: {len(changes)} referencias por actualizar, {resolved} correctas, {len(copies)} WebP por crear.")
