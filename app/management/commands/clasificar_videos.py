from dataclasses import dataclass
from pathlib import Path

from django.core.checks import Tags
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from app.models import Idioma, Videos

from .importar_catalogo import (
    VIDEO_RELATIONS,
    create_classifications,
    load_catalog_rows,
    lock_video_catalog,
    parse_catalog_rows,
    plan_classifications,
)


VIDEO_FIELDS = {"video", "nombre", "descripcion", "idioma", *VIDEO_RELATIONS}


@dataclass(frozen=True)
class VideoUpdate:
    video: Videos
    title: str | None
    description: str | None
    language: str | None
    relations: dict[str, tuple[str, ...]]


def is_valid_text(value, max_length):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= max_length


def is_source_id(value):
    return type(value) is int and value > 0


def read_updates(path):
    rows = load_catalog_rows(path)
    expected_titles = {}
    for row in rows:
        if not is_source_id(row.get("pk")):
            raise CommandError("Cada registro debe tener un PK de origen entero positivo.")
        fields = row["fields"]
        title = fields.get("nombre")
        if not is_valid_text(title, 100):
            raise CommandError("Cada registro debe tener un nombre válido de hasta 100 caracteres.")
        if row["model"] != Videos._meta.label_lower:
            if fields.keys() != {"nombre"}:
                raise CommandError("Cada clasificación debe contener solo su nombre.")
            continue

        key = fields.get("video")
        expected_title = row.get("nombre_esperado", title)
        if fields.keys() - VIDEO_FIELDS or not is_valid_text(key, 100) or not is_valid_text(expected_title, 100):
            raise CommandError(f"La fila {row['pk']} debe indicar la clave del video y sus metadatos válidos.")
        if "descripcion" in fields and not is_valid_text(fields["descripcion"], 1000):
            raise CommandError(f"La descripción de la fila {row['pk']} debe tener entre 1 y 1000 caracteres.")
        for field in VIDEO_RELATIONS:
            source_ids = fields.get(field, [])
            if not isinstance(source_ids, list) or not all(map(is_source_id, source_ids)):
                raise CommandError(f"Usa una lista de PK de origen en {field} para la fila {row['pk']}.")
            if len(source_ids) != len(set(source_ids)):
                raise CommandError(f"Hay referencias repetidas en {field} para la fila {row['pk']}.")
        language = fields.get("idioma")
        if language is not None and not is_source_id(language):
            raise CommandError(f"Usa un PK de origen o null en idioma para la fila {row['pk']}.")
        expected_titles[key] = expected_title

    return parse_catalog_rows(rows), expected_titles


def plan_updates(catalog, expected_titles):
    videos_by_key = {}
    targets = Videos.objects.filter(video__in=expected_titles).prefetch_related(*VIDEO_RELATIONS)
    for video in targets:
        key = video.video.name
        if key in videos_by_key:
            raise CommandError(f"Hay más de un video con la clave {key!r}.")
        videos_by_key[key] = video

    updates = []
    preserved_descriptions = []
    for entry in catalog[Videos].values():
        source = entry.object
        key = source.video.name
        video = videos_by_key.get(key)
        if video is None:
            raise CommandError(f"No se encontró el video con la clave {key!r}.")
        if video.nombre not in (expected_titles[key], source.nombre):
            raise CommandError(f"El título actual de {key!r} no coincide con el esperado.")

        title = source.nombre if source.nombre != video.nombre else None
        description = None
        if source.descripcion:
            if not video.descripcion.strip():
                description = source.descripcion
            elif video.descripcion != source.descripcion:
                preserved_descriptions.append(video)
        language = None
        if source.idioma_id is not None:
            requested_language = catalog[Idioma][source.idioma_id].object.nombre
            if video.idioma_id is None:
                language = requested_language
            elif video.idioma.nombre != requested_language:
                raise CommandError(
                    f"El idioma actual de {key!r} es {video.idioma.nombre!r}. "
                    f"El archivo indica {requested_language!r}."
                )
        relations = {}
        for field, model in VIDEO_RELATIONS.items():
            source_ids = entry.m2m_data.get(field, ())
            if source_ids:
                existing = {item.nombre for item in getattr(video, field).all()}
                requested = (catalog[model][pk].object.nombre for pk in source_ids)
                additions = tuple(name for name in requested if name not in existing)
                if additions:
                    relations[field] = additions
        if title or description or language or relations:
            updates.append(VideoUpdate(video, title, description, language, relations))
    return updates, preserved_descriptions


def apply_updates(catalog, expected_titles):
    with transaction.atomic():
        lock_video_catalog()
        updates, preserved_descriptions = plan_updates(catalog, expected_titles)
        ids_by_name, missing = plan_classifications(catalog)
        created = create_classifications(ids_by_name, missing)
        for update in updates:
            video = update.video
            fields = {}
            if update.title is not None:
                fields["nombre"] = update.title
            if update.description is not None:
                fields["descripcion"] = update.description
            if update.language is not None:
                fields["idioma_id"] = ids_by_name[Idioma][update.language]
            if fields:
                Videos.objects.filter(pk=video.pk).update(**fields)
            for field, names in update.relations.items():
                ids = [ids_by_name[VIDEO_RELATIONS[field]][name] for name in names]
                getattr(video, field).add(*ids)
    return updates, created, preserved_descriptions


class Command(BaseCommand):
    help = "Agrega clasificaciones y descripciones a videos existentes por su clave de archivo. Simula por defecto."
    requires_system_checks = [Tags.models]

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=Path, help="JSON con las clasificaciones y las claves de video.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Muestra los cambios sin escribir en la base.")
        mode.add_argument("--aplicar", action="store_true", help="Guarda los cambios en el catálogo.")

    def handle(self, *args, **options):
        catalog, expected_titles = read_updates(options["archivo"])
        apply = options["aplicar"]
        if apply and options["dry_run"]:
            raise CommandError("Elige un solo modo: --dry-run o --aplicar.")
        try:
            if apply:
                updates, classifications, preserved_descriptions = apply_updates(catalog, expected_titles)
            else:
                updates, preserved_descriptions = plan_updates(catalog, expected_titles)
                _, classifications = plan_classifications(catalog)
        except DatabaseError as error:
            message = "Comprueba la conexión y las migraciones de la base de datos de SoplaX."
            if apply:
                message = f"Se revirtió la actualización. {message}"
            raise CommandError(message) from error

        creation = "Se creó" if apply else "Se crearía"
        for model, name in classifications:
            self.stdout.write(f"{creation} {model._meta.verbose_name} {name!r}.")
        action = "Se actualizó" if apply else "Se actualizaría"
        for update in updates:
            video = update.video
            self.stdout.write(f"{action} video {video.pk} con clave {video.video.name!r}.")
            if update.title is not None:
                self.stdout.write(f"  Título: {video.nombre!r} → {update.title!r}.")
            if update.description is not None:
                self.stdout.write(f"  Descripción: {video.descripcion!r} → {update.description!r}.")
            if update.language is not None:
                self.stdout.write(f"  Idioma: {update.language!r}.")
            for field, names in update.relations.items():
                label = Videos._meta.get_field(field).verbose_name
                self.stdout.write(f"  {label.capitalize()}: agregar {', '.join(map(repr, names))}.")
        preserved = "Se conservó" if apply else "Se conservaría"
        for video in preserved_descriptions:
            self.stdout.write(f"{preserved} la descripción existente del video con clave {video.video.name!r}.")
        summary = "Aplicación" if apply else "Simulación"
        unchanged = len(catalog[Videos]) - len(updates)
        self.stdout.write(
            f"{summary}: {len(updates)} videos actualizados, {len(classifications)} clasificaciones nuevas, "
            f"{unchanged} sin cambios y {len(preserved_descriptions)} descripciones existentes conservadas."
        )
