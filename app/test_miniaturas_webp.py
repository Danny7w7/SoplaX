from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import TestCase, override_settings
from PIL import Image

from .models import Actor, Categoria, Idioma, Postura, Videos


class ConvertirMiniaturasWebpTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.media_root = Path(directory)
        self.enterContext(override_settings(
            MEDIA_ROOT=directory,
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            },
        ))
        self.storage = storages["default"]

        self.jpg = self.save_image("upload/photos/paisaje.JPG", "JPEG", "RGB", (1920, 1080))
        self.png = self.save_image("upload/photos/retrato.png", "PNG", "RGBA", (600, 1200))
        self.webp = self.save_image("upload/photos/webp/existente.webp", "WEBP", "RGB", (48, 28))
        self.storage.save("upload/videos/video.mp4", ContentFile(b"video sintetico"))

        self.landscape = self.create_video("Paisaje", self.jpg)
        self.shared = self.create_video("Miniatura compartida", self.jpg)
        self.portrait = self.create_video("Retrato", self.png)
        self.existing = self.create_video("WebP existente", self.webp)
        self.empty = self.create_video("Sin miniatura", "")

        language = Idioma.objects.create(nombre="Idioma de prueba")
        self.landscape.idioma = language
        self.landscape.save(update_fields=["idioma"])
        self.landscape.categorias.add(Categoria.objects.create(nombre="Categoría de prueba"))
        self.landscape.actores.add(Actor.objects.create(nombre="Actor de prueba"))
        self.landscape.posturas.add(Postura.objects.create(nombre="Postura de prueba"))

    def save_image(self, name, image_format, mode, dimensions):
        with BytesIO() as data, Image.new(mode, dimensions, "purple") as image:
            if mode == "RGBA":
                image.paste((0, 0, 0, 0), (0, 0, dimensions[0] // 2, dimensions[1] // 2))
            image.save(data, image_format)
            return self.storage.save(name, ContentFile(data.getvalue()))

    def create_video(self, title, thumbnail):
        return Videos.objects.create(
            nombre=title,
            descripcion="Descripción de prueba",
            miniatura=thumbnail,
            video="upload/videos/video.mp4",
            visitas=42,
        )

    def database_snapshot(self):
        tables = (
            Videos, Categoria, Actor, Postura, Idioma,
            Videos.categorias.through, Videos.actores.through, Videos.posturas.through,
        )
        return {model: list(model.objects.order_by("pk").values()) for model in tables}

    def storage_snapshot(self):
        return {
            path.relative_to(self.media_root).as_posix(): path.read_bytes()
            for path in self.media_root.rglob("*")
            if path.is_file()
        }

    def run_command(self, *args, **options):
        output = StringIO()
        call_command("convertir_miniaturas_webp", *args, stdout=output, stderr=StringIO(), **options)
        return output.getvalue()

    def assert_webp(self, name, dimensions, *, transparent=False):
        self.assertTrue(name.startswith("upload/photos/webp/"))
        self.assertTrue(name.endswith(".webp"))
        with self.storage.open(name, "rb") as file, Image.open(file) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, dimensions)
            if transparent:
                alpha = image.getchannel("A")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertEqual(alpha.getpixel((dimensions[0] - 1, dimensions[1] - 1)), 255)

    def test_simulacion_informa_el_plan_sin_escribir(self):
        original_rows = self.database_snapshot()
        original_files = self.storage_snapshot()

        def reject_writes(execute, sql, params, many, context):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(reject_writes),
            patch.object(self.storage, "save", wraps=self.storage.save) as save,
            patch.object(self.storage, "delete", wraps=self.storage.delete) as delete,
        ):
            output = self.run_command()
            self.assertEqual(self.run_command("--dry-run"), output)

        self.assertIn(self.jpg, output)
        self.assertIn(self.png, output)
        self.assertIn("upload/photos/webp/", output)
        save.assert_not_called()
        delete.assert_not_called()
        self.assertEqual(self.database_snapshot(), original_rows)
        self.assertEqual(self.storage_snapshot(), original_files)

    def test_aplicar_convierte_miniaturas_y_es_idempotente(self):
        expected_rows = self.database_snapshot()
        original_files = self.storage_snapshot()

        self.run_command(aplicar=True)

        for video in (self.landscape, self.shared, self.portrait):
            video.refresh_from_db()
        landscape_webp = self.landscape.miniatura.name
        portrait_webp = self.portrait.miniatura.name
        self.assertEqual(self.shared.miniatura.name, landscape_webp)
        self.assertNotEqual(landscape_webp, portrait_webp)
        self.assert_webp(landscape_webp, (960, 540))
        self.assert_webp(portrait_webp, (270, 540), transparent=True)

        converted = {
            self.landscape.pk: landscape_webp,
            self.shared.pk: landscape_webp,
            self.portrait.pk: portrait_webp,
        }
        for row in expected_rows[Videos]:
            row["miniatura"] = converted.get(row["id"], row["miniatura"])
        self.assertEqual(self.database_snapshot(), expected_rows)
        applied_files = self.storage_snapshot()
        self.assertEqual(set(applied_files) - set(original_files), {landscape_webp, portrait_webp})
        for name, data in original_files.items():
            self.assertEqual(applied_files[name], data)

        with patch.object(self.storage, "save", wraps=self.storage.save) as save:
            self.run_command(aplicar=True)
        save.assert_not_called()
        self.assertEqual(self.database_snapshot(), expected_rows)
        self.assertEqual(self.storage_snapshot(), applied_files)

    def test_rechaza_una_imagen_danada_sin_cambiar_el_catalogo(self):
        bad_file = self.storage.save("upload/photos/danada.png", ContentFile(b"imagen invalida"))
        self.create_video("Miniatura dañada", bad_file)
        original_rows = self.database_snapshot()
        original_files = self.storage_snapshot()

        with self.assertRaises(CommandError) as error:
            self.run_command(aplicar=True)

        self.assertIn(bad_file, str(error.exception))
        self.assertEqual(self.database_snapshot(), original_rows)
        self.assertEqual(self.storage_snapshot(), original_files)

    def test_error_al_actualizar_revierte_la_base_y_limpia_webp_nuevos(self):
        original_rows = self.database_snapshot()
        original_files = self.storage_snapshot()
        update_attempted = False

        def fail_after_thumbnail_update(execute, sql, params, many, context):
            nonlocal update_attempted
            result = execute(sql, params, many, context)
            normalized_sql = sql.lstrip().upper()
            if normalized_sql.startswith('UPDATE "APP_VIDEOS"') and '"MINIATURA"' in normalized_sql:
                update_attempted = True
                self.assertTrue(set(self.storage_snapshot()) - set(original_files))
                raise DatabaseError("Fallo simulado al actualizar una miniatura")
            return result

        with connection.execute_wrapper(fail_after_thumbnail_update), self.assertRaises(CommandError):
            self.run_command(aplicar=True)

        self.assertTrue(update_attempted)
        self.assertEqual(self.database_snapshot(), original_rows)
        self.assertEqual(self.storage_snapshot(), original_files)
