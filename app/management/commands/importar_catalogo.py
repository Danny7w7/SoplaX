import json
from pathlib import Path

from django.core import serializers
from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.base import DeserializationError
from django.db import DatabaseError, connection, transaction

from app.models import Actor, Categoria, Idioma, Postura, Videos


CLASSIFICATIONS = (Actor, Categoria, Idioma, Postura)
CATALOG_MODELS = (*CLASSIFICATIONS, Videos)
CATALOG_LABELS = {model._meta.label_lower for model in CATALOG_MODELS}
VIDEO_RELATIONS = {"actores": Actor, "categorias": Categoria, "posturas": Postura}


def load_catalog_rows(path):
    try:
        with path.open(encoding="utf-8-sig") as fixture:
            rows = json.load(fixture)
    except OSError as error:
        raise CommandError(f"No se pudo abrir el catálogo en {path}.") from error
    except ValueError as error:
        raise CommandError("El catálogo debe ser un archivo JSON válido en UTF-8.") from error

    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("model"), str)
        or row["model"] not in CATALOG_LABELS
        or not isinstance(row.get("fields"), dict)
        for row in rows
    ):
        raise CommandError("El archivo debe contener únicamente registros del catálogo de SoplaX.")
    return rows


def parse_catalog_rows(rows):
    catalog = {model: {} for model in CATALOG_MODELS}
    try:
        for entry in serializers.deserialize("python", rows):
            source = entry.object
            records = catalog[type(source)]
            if source.pk is None or source.pk in records:
                raise CommandError("El archivo contiene identificadores de origen inválidos o repetidos.")
            records[source.pk] = entry
    except (DeserializationError, FieldDoesNotExist, TypeError, ValueError) as error:
        raise CommandError("El archivo contiene datos de catálogo inválidos.") from error

    video_keys = [entry.object.video.name for entry in catalog[Videos].values()]
    if not all(video_keys) or len(set(video_keys)) != len(video_keys):
        raise CommandError("Cada video debe tener una clave de archivo única en el catálogo de origen.")

    for model in CLASSIFICATIONS:
        names = [entry.object.nombre for entry in catalog[model].values()]
        if not all(names) or len(set(names)) != len(names):
            raise CommandError(f"El archivo contiene nombres inválidos o repetidos para {model._meta.verbose_name_plural}.")

    for entry in catalog[Videos].values():
        language = entry.object.idioma_id
        references = {model: entry.m2m_data.get(field, ()) for field, model in VIDEO_RELATIONS.items()}
        references[Idioma] = () if language is None else (language,)
        if any(set(source_ids).difference(catalog[model]) for model, source_ids in references.items()):
            raise CommandError("Un video usa una clasificación que falta en el archivo.")
    return catalog


def read_catalog(path):
    return parse_catalog_rows(load_catalog_rows(path))


def plan_classifications(catalog):
    ids_by_name = {}
    missing = []
    for model in CLASSIFICATIONS:
        names = [entry.object.nombre for entry in catalog[model].values()]
        found = dict(model.objects.filter(nombre__in=names).values_list("nombre", "pk"))
        ids_by_name[model] = found
        missing.extend((model, name) for name in names if name not in found)
    return ids_by_name, missing


def plan_import(catalog):
    ids_by_name, missing = plan_classifications(catalog)
    pending = []
    for entry in catalog[Videos].values():
        key = entry.object.video.name
        matches = list(Videos.objects.filter(video=key).values_list("pk", flat=True)[:2])
        if len(matches) > 1:
            raise CommandError(f"Hay más de un video en el destino con la clave {key!r}.")
        if not matches:
            pending.append(entry)
    return ids_by_name, missing, pending


def lock_video_catalog():
    if connection.vendor == "postgresql":
        # Serializa el plan y la escritura porque la clave del video no es única en el esquema.
        table = connection.ops.quote_name(Videos._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE")


def create_classifications(ids_by_name, missing):
    created = []
    for model, name in missing:
        classification, was_created = model.objects.get_or_create(nombre=name)
        ids_by_name[model][name] = classification.pk
        if was_created:
            created.append((model, name))
    return created


def apply_import(catalog):
    with transaction.atomic():
        lock_video_catalog()
        ids_by_name, missing, pending = plan_import(catalog)
        created = create_classifications(ids_by_name, missing)

        target_ids = {
            model: {
                source_id: ids_by_name[model][entry.object.nombre]
                for source_id, entry in catalog[model].items()
            }
            for model in CLASSIFICATIONS
        }
        for entry in pending:
            video = entry.object
            if video.idioma_id is not None:
                video.idioma_id = target_ids[Idioma][video.idioma_id]
            video.pk = None
            video.save(force_insert=True)
            for field, model in VIDEO_RELATIONS.items():
                getattr(video, field).set([target_ids[model][pk] for pk in entry.m2m_data.get(field, ())])
    return created, pending


class Command(BaseCommand):
    help = "Simula la importación de un catálogo de SoplaX exportado con dumpdata."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=Path, help="Ruta del catálogo JSON de SoplaX.")
        parser.add_argument("--aplicar", action="store_true", help="Inserta los registros que faltan.")

    def handle(self, *args, **options):
        catalog = read_catalog(options["archivo"])
        apply = options["aplicar"]
        try:
            if apply:
                classifications, videos = apply_import(catalog)
            else:
                _, classifications, videos = plan_import(catalog)
        except DatabaseError as error:
            message = "Comprueba la conexión y las migraciones de la base de datos de SoplaX."
            if apply:
                message = f"Se revirtieron los cambios. {message}"
            raise CommandError(message) from error

        verb = "Se insertó" if apply else "Se insertaría"
        for model, name in classifications:
            self.stdout.write(f"{verb} {model._meta.verbose_name} {name!r}.")
        for entry in videos:
            self.stdout.write(f"{verb} video {entry.object.video.name!r}.")

        summary = "Se insertaron" if apply else "Se insertarían"
        existing = len(catalog[Videos]) - len(videos)
        self.stdout.write(
            f"{summary} {len(videos)} videos y {len(classifications)} clasificaciones. "
            f"Ya existen {existing} videos. Modificaciones y eliminaciones de registros existentes: 0."
        )
