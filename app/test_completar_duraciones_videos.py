from io import StringIO
from unittest.mock import call, patch

from django.contrib.admin.models import LogEntry
from django.core.files.storage import InMemoryStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import TestCase

from .models import Videos


COMMAND = "completar_duraciones_videos"
COMMAND_MODULE = f"app.management.commands.{COMMAND}"


class CompletarDuracionesVideosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first = cls.create_video("Primero", "upload/videos/primero.mp4")
        cls.shared = cls.create_video("Comparte archivo", cls.first.video.name)
        cls.second = cls.create_video("Segundo", "upload/videos/segundo.mp4")
        cls.create_video("Con duración", "upload/videos/registrado.mp4", duration=95)
        cls.create_video("Sin archivo", "")

    @staticmethod
    def create_video(title, key, *, duration=None):
        return Videos.objects.create(
            nombre=title,
            descripcion="Video de prueba",
            miniatura="upload/Miniaturas/Premium/prueba.webp",
            video=key,
            visitas=13,
            duracion_segundos=duration,
        )

    def setUp(self):
        self.storage = InMemoryStorage()
        self.enterContext(patch.object(Videos._meta.get_field("video"), "storage", self.storage))
        for operation in ("save", "delete"):
            self.enterContext(
                patch.object(self.storage, operation, side_effect=AssertionError("Escritura de archivo"))
            )
        self.probe = self.enterContext(
            patch(f"{COMMAND_MODULE}.read_stored_video_duration", side_effect=self.read_duration)
        )

    def read_duration(self, storage, key):
        self.assertIs(storage, self.storage)
        return {self.first.video.name: 125, self.second.video.name: 3723}[key]

    def snapshot(self):
        return list(Videos.objects.order_by("pk").values())

    def run_command(self, *args, stderr=None):
        stdout = StringIO()
        call_command(COMMAND, *args, stdout=stdout, stderr=stderr or StringIO())
        return stdout.getvalue()

    def require_read_queries(self, execute, sql, params, many, context):
        self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
        return execute(sql, params, many, context)

    def test_simulacion_predeterminada_indica_duraciones_sin_escribir(self):
        before = self.snapshot()

        with connection.execute_wrapper(self.require_read_queries):
            output = self.run_command()
            self.assertEqual(self.run_command("--dry-run"), output)

        self.assertIn("Simulación: 3 duraciones por completar", output)
        self.assertIn(f"Video {self.first.pk}: duración pendiente → 125 s.", output)
        self.assertIn(f"Video {self.shared.pk}: duración pendiente → 125 s.", output)
        self.assertIn(f"Video {self.second.pk}: duración pendiente → 3723 s.", output)
        self.assertIn("Duraciones ya registradas: 1. Videos sin archivo: 1.", output)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            self.probe.call_args_list,
            [call(self.storage, key) for key in (self.first.video.name, self.second.video.name)] * 2,
        )

    def test_aplicar_solo_actualiza_las_duraciones_pendientes_y_es_idempotente(self):
        expected = self.snapshot()
        durations = {self.first.pk: 125, self.shared.pk: 125, self.second.pk: 3723}
        for row in expected:
            row["duracion_segundos"] = durations.get(row["id"], row["duracion_segundos"])

        self.assertIn("Aplicado: 3 duraciones completadas", self.run_command("--aplicar"))
        self.assertEqual(self.snapshot(), expected)
        self.probe.reset_mock()
        with connection.execute_wrapper(self.require_read_queries):
            self.assertIn("Aplicado: 0 duraciones completadas", self.run_command("--aplicar"))
        self.probe.assert_not_called()
        self.assertEqual(self.snapshot(), expected)
        self.assertFalse(LogEntry.objects.exists())

    def test_error_de_lectura_informa_el_video_y_cancela_el_lote(self):
        from .video_durations import VideoDurationError

        before = self.snapshot()
        self.probe.side_effect = [125, VideoDurationError("El objeto no está disponible.")]
        stderr = StringIO()

        with connection.execute_wrapper(self.require_read_queries), self.assertRaises(CommandError):
            self.run_command("--aplicar", stderr=stderr)

        self.assertIn(f"Video {self.second.pk}: El objeto no está disponible.", stderr.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_cambio_concurrente_de_archivo_revierte_las_otras_actualizaciones(self):
        replacement = "upload/videos/reemplazo.mp4"
        expected = self.snapshot()
        for row in expected:
            if row["id"] == self.second.pk:
                row["video"] = replacement

        def replace_video_while_reading(storage, key):
            if key == self.second.video.name:
                Videos.objects.filter(pk=self.second.pk).update(video=replacement)
            return self.read_duration(storage, key)

        self.probe.side_effect = replace_video_while_reading
        with self.assertRaisesMessage(
            CommandError, f"El archivo o la duración del video {self.second.pk} cambió"
        ):
            self.run_command("--aplicar")

        self.assertEqual(self.snapshot(), expected)

    def test_error_de_base_de_datos_durante_la_aplicacion_revierte_todo_el_lote(self):
        before = self.snapshot()
        writes = 0

        def fail_second_write(execute, sql, params, many, context):
            nonlocal writes
            result = execute(sql, params, many, context)
            if sql.lstrip().upper().startswith('UPDATE "APP_VIDEOS"'):
                writes += 1
                if writes == 2:
                    raise DatabaseError("Fallo simulado al guardar la duración")
            return result

        with connection.execute_wrapper(fail_second_write), self.assertRaises(CommandError):
            self.run_command("--aplicar")

        self.assertEqual(writes, 2)
        self.assertEqual(self.snapshot(), before)

    def test_simular_y_aplicar_son_mutuamente_excluyentes(self):
        with self.assertRaises(CommandError):
            self.run_command("--dry-run", "--aplicar")
        self.probe.assert_not_called()
