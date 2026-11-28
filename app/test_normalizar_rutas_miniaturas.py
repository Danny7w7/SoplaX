import json
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase, override_settings

from .models import Videos


COMMAND = "app.management.commands.normalizar_rutas_miniaturas"


@override_settings(DEVELOPMENT=True)
class NormalizarRutasMiniaturasTests(TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / "miniaturas.json"
        self.storage = InMemoryStorage()
        self.enterContext(patch.object(Videos._meta.get_field("miniatura"), "storage", self.storage))
        self.premium = self.create_video("uno", "upload/Miniaturas/Premium/antigua.jpg", premium=True)
        self.free = self.create_video("dos", "upload/photos/webp/origen.webp", premium=False)
        self.create_video("fuera-del-mapa", "upload/photos/otra.jpg", premium=True)
        self.create_video("sin-miniatura", "", premium=True)
        self.contents = (b"webp sintetica uno", b"webp sintetica dos")
        self.entries = [
            self.entry(self.premium, "Premium", "nueva-uno", self.contents[0]),
            self.entry(self.free, "NoPremium", "nueva-dos", self.contents[1]),
        ]
        self.write_manifest()

    def create_video(self, name, thumbnail, *, premium):
        return Videos.objects.create(
            nombre=name,
            descripcion="Miniatura de prueba",
            es_premium=premium,
            miniatura=thumbnail,
            video=f"upload/videos/{name}.mp4",
            visitas=13,
        )

    def entry(self, video, segment, slug, content):
        prefix = f"upload/Miniaturas/{segment}/"
        return {
            "video": video.video.name,
            "es_premium": video.es_premium,
            "origenes": [video.miniatura.name],
            "webp_actual": prefix + sha256(content).hexdigest() + ".webp",
            "destino": prefix + slug + ".webp",
        }

    def write_manifest(self):
        self.path.write_text(json.dumps(self.entries), encoding="utf-8")

    def snapshot(self):
        return list(Videos.objects.order_by("pk").values())

    def run_command(self, *args):
        output = StringIO()
        call_command("normalizar_rutas_miniaturas", str(self.path), *args, stdout=output)
        return output.getvalue()

    def test_simulacion_de_reparacion_local_solo_lee_la_base(self):
        before = self.snapshot()

        def reject_writes(execute, sql, params, many, context):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(reject_writes),
            patch.object(self.storage, "open", side_effect=AssertionError("Consulta al almacenamiento")),
        ):
            output = self.run_command("--usar-webp-existentes")
            self.assertEqual(output, self.run_command("--usar-webp-existentes", "--dry-run"))

        self.assertIn("Simulación: 2 referencias por actualizar", output)
        self.assertIn(self.entries[0]["webp_actual"], output)
        self.assertEqual(self.snapshot(), before)

    def test_repara_solo_las_referencias_indicadas_y_es_idempotente(self):
        expected = self.snapshot()
        changed = {entry["video"]: entry["webp_actual"] for entry in self.entries}
        for row in expected:
            row["miniatura"] = changed.get(row["video"], row["miniatura"])

        self.assertIn(
            "Aplicado: 2 referencias actualizadas",
            self.run_command("--usar-webp-existentes", "--aplicar"),
        )
        self.assertEqual(self.snapshot(), expected)
        self.assertIn(
            "Aplicado: 0 referencias actualizadas",
            self.run_command("--usar-webp-existentes", "--aplicar"),
        )
        self.assertEqual(self.snapshot(), expected)

    def test_adopta_nombres_una_vez_publicados_y_no_vuelve_a_los_hashes(self):
        for entry, content in zip(self.entries, self.contents, strict=True):
            self.storage.save(entry["destino"], ContentFile(content))

        with (
            patch.object(self.storage, "save", side_effect=AssertionError("Escritura de archivo")),
            patch.object(self.storage, "delete", side_effect=AssertionError("Eliminación de archivo")),
        ):
            self.run_command("--aplicar")
            self.assertIn("Aplicado: 0 referencias actualizadas", self.run_command("--usar-webp-existentes", "--aplicar"))
        self.premium.refresh_from_db()
        self.free.refresh_from_db()
        self.assertEqual(self.premium.miniatura.name, self.entries[0]["destino"])
        self.assertEqual(self.free.miniatura.name, self.entries[1]["destino"])

    def test_destino_ausente_o_con_contenido_distinto_impide_la_aplicacion(self):
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, "todavía no está publicada"):
            self.run_command("--aplicar")
        self.storage.save(self.entries[0]["destino"], ContentFile(b"otro contenido"))
        with self.assertRaisesMessage(CommandError, "no coincide"):
            self.run_command("--aplicar")
        self.assertEqual(self.snapshot(), before)

    def test_clave_de_video_duplicada_o_referencia_inesperada_impide_la_aplicacion(self):
        Videos.objects.filter(pk=self.free.pk).update(video=self.premium.video.name)
        with self.assertRaisesMessage(CommandError, "más de un registro"):
            self.run_command("--usar-webp-existentes", "--aplicar")
        Videos.objects.filter(pk=self.free.pk).update(video=self.free.video.name, miniatura="upload/otra.webp")
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, "miniatura inesperada"):
            self.run_command("--usar-webp-existentes", "--aplicar")
        self.assertEqual(self.snapshot(), before)

    def test_error_en_segunda_escritura_revierte_el_catalogo(self):
        before = self.snapshot()
        writes = 0

        def fail_second_write(execute, sql, params, many, context):
            nonlocal writes
            result = execute(sql, params, many, context)
            if sql.lstrip().upper().startswith('UPDATE "APP_VIDEOS"'):
                writes += 1
                if writes == 2:
                    raise DatabaseError("Fallo simulado")
            return result

        with connection.execute_wrapper(fail_second_write), self.assertRaises(CommandError):
            self.run_command("--usar-webp-existentes", "--aplicar")
        self.assertEqual(writes, 2)
        self.assertEqual(self.snapshot(), before)

    def test_publica_nombres_antes_de_actualizar_y_reutiliza_las_copias(self):
        before = self.snapshot()
        for entry, content in zip(self.entries, self.contents, strict=True):
            self.storage.save(entry["webp_actual"], ContentFile(content))

        def publish(storage, reference, content):
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(storage.save(reference.destination, ContentFile(content)), reference.destination)
            return True

        with (
            patch(f"{COMMAND}.is_compose_catalog", return_value=True),
            patch(f"{COMMAND}.publish_webp", side_effect=publish) as upload,
            patch.object(self.storage, "delete", side_effect=AssertionError("Eliminación de archivo")),
        ):
            output = self.run_command("--dry-run")
            self.assertIn("2 WebP por crear", output)
            self.assertEqual(self.snapshot(), before)
            upload.assert_not_called()

            self.assertIn("2 WebP creadas", self.run_command("--aplicar"))
            self.assertEqual(upload.call_count, 2)
            self.assertIn("Aplicado: 0 referencias actualizadas", self.run_command("--aplicar"))
            self.assertEqual(upload.call_count, 2)

        for entry, content in zip(self.entries, self.contents, strict=True):
            self.assertEqual(self.storage.open(entry["webp_actual"]).read(), content)
            self.assertEqual(self.storage.open(entry["destino"]).read(), content)

    @override_settings(DEVELOPMENT=False)
    def test_rechaza_una_base_que_no_es_la_de_compose(self):
        with self.assertRaisesMessage(CommandError, "PostgreSQL de Compose"):
            self.run_command("--aplicar")


class PublicarMiniaturaWebpTests(SimpleTestCase):
    def test_s3_solo_crea_el_destino_si_esta_libre(self):
        from .management.commands.normalizar_rutas_miniaturas import publish_webp

        storage = Mock()
        storage.bucket_name = "bucket-de-prueba"
        storage._normalize_name.side_effect = lambda key: key
        reference = Mock(destination="upload/Miniaturas/Premium/legible.webp")
        client = storage.connection.meta.client
        self.assertTrue(publish_webp(storage, reference, b"webp"))
        client.put_object.assert_called_once_with(
            Bucket=storage.bucket_name,
            Key=reference.destination,
            Body=b"webp",
            ContentType="image/webp",
            IfNoneMatch="*",
        )

        client.put_object.side_effect = ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        with patch(f"{COMMAND}.read_verified_webp", return_value=b"webp") as read:
            self.assertFalse(publish_webp(storage, reference, b"webp"))
            read.assert_called_once_with(storage, reference.destination, reference)
