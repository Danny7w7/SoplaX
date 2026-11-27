import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.admin.models import LogEntry
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import Actor, Categoria, Idioma, Postura, Videos


class ClasificarVideosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.previous_category = Categoria.objects.create(nombre="Categoría anterior")
        cls.shared_category = Categoria.objects.create(pk=17, nombre="Naturaleza")
        cls.previous_actor = Actor.objects.create(nombre="Intérprete anterior")
        cls.previous_pose = Postura.objects.create(nombre="Posición anterior")
        cls.english = Idioma.objects.create(nombre="Inglés")
        cls.target = Videos.objects.create(
            pk=70,
            nombre="Sendero original",
            descripcion="",
            miniatura="upload/photos/sendero.webp",
            video="upload/videos/sendero.mp4",
            visitas=27,
        )
        cls.target.categorias.add(cls.previous_category)
        cls.target.actores.add(cls.previous_actor)
        cls.target.posturas.add(cls.previous_pose)
        cls.second = Videos.objects.create(
            pk=71, nombre="Concierto", video="upload/videos/concierto.mp4", visitas=5, idioma=cls.english
        )
        cls.second.categorias.add(cls.shared_category)
        cls.second.actores.add(cls.previous_actor)
        cls.second.posturas.add(cls.previous_pose)
        cls.unrelated = Videos.objects.create(
            pk=1, nombre="Video ajeno", video="upload/videos/ajeno.mp4", visitas=19
        )

    def fixture_rows(self):
        return [
            {"model": "app.categoria", "pk": 1, "fields": {"nombre": "Naturaleza"}},
            {"model": "app.categoria", "pk": 2, "fields": {"nombre": "Excursión"}},
            {"model": "app.actor", "pk": 1, "fields": {"nombre": "Intérprete nuevo"}},
            {"model": "app.idioma", "pk": 1, "fields": {"nombre": "Español"}},
            {"model": "app.postura", "pk": 1, "fields": {"nombre": "Posición nueva"}},
            {
                "model": "app.videos",
                "pk": 1,
                "nombre_esperado": "Sendero original",
                "fields": {
                    "video": self.target.video.name,
                    "nombre": "Sendero clasificado",
                    "descripcion": "Descripción nueva y comprobada de la escena.",
                    "categorias": [1, 2],
                    "actores": [1],
                    "posturas": [1],
                    "idioma": 1,
                },
            },
            {
                "model": "app.videos",
                "pk": 2,
                "fields": {
                    "video": self.second.video.name,
                    "nombre": self.second.nombre,
                    "categorias": [],
                    "actores": [],
                    "posturas": [],
                    "idioma": None,
                },
            },
        ]

    def database_snapshot(self):
        models = (
            Videos, Categoria, Actor, Idioma, Postura, LogEntry,
            Videos.categorias.through, Videos.actores.through, Videos.posturas.through,
        )
        return {model: list(model.objects.order_by("pk").values()) for model in models}

    def run_command(self, *args, rows=None):
        output = StringIO()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "clasificacion.json"
            path.write_text(json.dumps(self.fixture_rows() if rows is None else rows), encoding="utf-8")
            call_command("clasificar_videos", str(path), *args, stdout=output)
        return output.getvalue()

    def test_simula_por_defecto_sin_escrituras(self):
        original = self.database_snapshot()
        with CaptureQueriesContext(connection) as queries:
            output = self.run_command()
            self.assertEqual(self.run_command("--dry-run"), output)

        self.assertTrue(queries.captured_queries)
        for query in queries.captured_queries:
            self.assertTrue(query["sql"].lstrip().upper().startswith("SELECT "), query["sql"])
        for value in (
            self.target.video.name, "Sendero original", "Sendero clasificado",
            "Descripción nueva y comprobada de la escena.", "Excursión", "Español",
        ):
            self.assertIn(value, output)
        self.assertEqual(self.database_snapshot(), original)

    def test_aplicar_clasifica_por_clave_y_es_idempotente(self):
        original = self.database_snapshot()
        self.run_command("--aplicar")

        self.target.refresh_from_db()
        self.assertEqual(self.target.nombre, "Sendero clasificado")
        self.assertEqual(self.target.descripcion, "Descripción nueva y comprobada de la escena.")
        self.assertEqual(self.target.idioma.nombre, "Español")
        self.assertCountEqual(
            self.target.categorias.all(), [self.previous_category, self.shared_category, Categoria.objects.get(nombre="Excursión")]
        )
        self.assertCountEqual(
            self.target.actores.values_list("nombre", flat=True), ["Intérprete anterior", "Intérprete nuevo"]
        )
        self.assertCountEqual(
            self.target.posturas.values_list("nombre", flat=True), ["Posición anterior", "Posición nueva"]
        )

        applied = self.database_snapshot()
        expected_videos = original[Videos]
        target_row = next(row for row in expected_videos if row["id"] == self.target.pk)
        target_row.update(
            nombre="Sendero clasificado",
            descripcion="Descripción nueva y comprobada de la escena.",
            idioma_id=self.target.idioma_id,
        )
        self.assertEqual(applied[Videos], expected_videos)
        for model in (Videos.categorias.through, Videos.actores.through, Videos.posturas.through):
            self.assertEqual(
                [row for row in applied[model] if row["videos_id"] != self.target.pk],
                [row for row in original[model] if row["videos_id"] != self.target.pk],
            )
        self.assertEqual(Categoria.objects.count(), 3)

        with CaptureQueriesContext(connection) as queries:
            self.run_command("--aplicar")
        for query in queries.captured_queries:
            self.assertFalse(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")))
        self.assertEqual(self.database_snapshot(), applied)

    def test_rechaza_referencias_e_identidades_invalidas_sin_escribir(self):
        original = self.database_snapshot()
        for field, value in (
            ("idioma", 999), ("video", "upload/videos/desconocido.mp4"),
            ("nombre_esperado", "Título inesperado"), ("descripcion", " " * 1001),
        ):
            with self.subTest(field=field):
                rows = self.fixture_rows()
                if field == "nombre_esperado":
                    rows[-2][field] = value
                else:
                    rows[-2]["fields"][field] = value
                with self.assertRaises(CommandError):
                    self.run_command("--aplicar", rows=rows)
                self.assertEqual(self.database_snapshot(), original)

    def test_rechaza_clave_duplicada_en_el_catalogo(self):
        Videos.objects.create(nombre="Otro título", video=self.target.video.name, visitas=4)
        original = self.database_snapshot()
        with self.assertRaises(CommandError):
            self.run_command("--aplicar")
        self.assertEqual(self.database_snapshot(), original)

    def test_respeta_un_idioma_existente_incompatible(self):
        Videos.objects.filter(pk=self.target.pk).update(idioma=self.english)
        original = self.database_snapshot()
        with self.assertRaises(CommandError):
            self.run_command("--aplicar")
        self.assertEqual(self.database_snapshot(), original)

    def test_conserva_una_descripcion_existente(self):
        Videos.objects.filter(pk=self.target.pk).update(descripcion="Reseña escrita previamente")
        self.run_command("--aplicar")
        self.target.refresh_from_db()
        self.assertEqual(self.target.descripcion, "Reseña escrita previamente")
        applied = self.database_snapshot()
        self.run_command("--aplicar")
        self.assertEqual(self.database_snapshot(), applied)

    def test_siembra_clasificaciones_sin_video_asociado(self):
        rows = [
            {"model": "app.categoria", "pk": 1, "fields": {"nombre": "Categoría futura"}},
            {"model": "app.actor", "pk": 1, "fields": {"nombre": "Actriz futura"}},
            {"model": "app.postura", "pk": 1, "fields": {"nombre": "Postura futura"}},
        ]
        original = self.database_snapshot()
        with CaptureQueriesContext(connection) as queries:
            output = self.run_command("--dry-run", rows=rows)
        self.assertTrue(queries.captured_queries)
        for query in queries.captured_queries:
            self.assertTrue(query["sql"].lstrip().upper().startswith("SELECT "), query["sql"])
        for name in ("Categoría futura", "Actriz futura", "Postura futura"):
            self.assertIn(name, output)
        self.assertIn("0 videos actualizados, 3 clasificaciones nuevas", output)
        self.assertEqual(self.database_snapshot(), original)

        self.run_command("--aplicar", rows=rows)
        self.assertTrue(Categoria.objects.filter(nombre="Categoría futura").exists())
        self.assertTrue(Actor.objects.filter(nombre="Actriz futura").exists())
        self.assertTrue(Postura.objects.filter(nombre="Postura futura").exists())
        applied = self.database_snapshot()
        self.assertIn("0 clasificaciones nuevas", self.run_command("--dry-run", rows=rows))
        self.run_command("--aplicar", rows=rows)
        self.assertEqual(self.database_snapshot(), applied)

    def test_revierte_el_catalogo_si_falla_despues_de_actualizar_un_video(self):
        original = self.database_snapshot()
        updated = False

        def fail_after_update(execute, sql, params, many, context):
            nonlocal updated
            result = execute(sql, params, many, context)
            statement = sql.lstrip().upper()
            if statement.startswith('UPDATE "APP_VIDEOS"') and '"NOMBRE"' in statement:
                updated = True
                raise DatabaseError("Fallo simulado al actualizar el título")
            return result

        with connection.execute_wrapper(fail_after_update), self.assertRaises(CommandError):
            self.run_command("--aplicar")
        self.assertTrue(updated)
        self.assertEqual(self.database_snapshot(), original)
