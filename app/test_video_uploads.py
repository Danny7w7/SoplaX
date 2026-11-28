from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Actor, Categoria, Idioma, Postura, Usuario, Videos


MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isommp42"


class VideoUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        permission = Permission.objects.get(content_type__app_label="app", codename="add_videos")
        change_permission = Permission.objects.get(content_type__app_label="app", codename="change_videos")
        cls.publisher = Usuario.objects.create_user(username="publisher", is_staff=True)
        cls.publisher.user_permissions.add(permission, change_permission)
        cls.viewer = Usuario.objects.create_user(username="viewer", is_staff=True)
        cls.member = Usuario.objects.create_user(username="member")
        cls.member.user_permissions.add(permission)

    def setUp(self):
        self.media_root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            MEDIA_ROOT=self.media_root,
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            },
        ))
        self.storage = storages["default"]
        self.upload_url = reverse("admin:app_videos_add")

    def upload_data(self, **overrides):
        with BytesIO() as thumbnail, Image.new("RGB", (64, 36), "purple") as image:
            image.save(thumbnail, "WEBP")
            image_bytes = thumbnail.getvalue()
        return {
            "nombre": "Video de prueba",
            "descripcion": "Descripción para el catálogo",
            "es_premium": "on",
            "video": SimpleUploadedFile("video.mp4", MP4_HEADER, content_type="video/mp4"),
            "miniatura": SimpleUploadedFile("miniatura.webp", image_bytes, content_type="image/webp"),
            "_publish": "1",
            **overrides,
        }

    def saved_files(self):
        return sorted(
            path.relative_to(self.media_root).as_posix()
            for path in self.media_root.rglob("*")
            if path.is_file()
        )

    def assert_no_publication(self):
        self.assertFalse(Videos.objects.exists())
        self.assertFalse(LogEntry.objects.exists())

    def test_upload_requires_staff_and_add_permission(self):
        login_url = reverse("admin:login")
        self.assertRedirects(self.client.get(self.upload_url), f"{login_url}?next={self.upload_url}")
        self.client.force_login(self.member)
        response = self.client.post(self.upload_url, self.upload_data())
        self.assertRedirects(response, f"{login_url}?next={self.upload_url}")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.upload_url).status_code, 403)
        self.assertEqual(self.client.post(self.upload_url, self.upload_data()).status_code, 403)
        self.assert_no_publication()
        self.assertEqual(self.saved_files(), [])

    def test_upload_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.publisher)
        self.assertEqual(client.post(self.upload_url, self.upload_data()).status_code, 403)
        self.assert_no_publication()
        self.assertEqual(self.saved_files(), [])

    def test_staff_can_publish_with_catalog_metadata(self):
        self.client.force_login(self.publisher)
        category = Categoria.objects.create(nombre="Categoría de prueba")
        actor = Actor.objects.create(nombre="Intérprete de prueba")
        language = Idioma.objects.create(nombre="Español")
        position = Postura.objects.create(nombre="Postura de prueba")
        data = self.upload_data(
            categorias=[category.pk],
            actores=[actor.pk],
            idioma=language.pk,
            posturas=[position.pk],
            visitas=99,
        )
        response = self.client.post(self.upload_url, data, follow=True)

        self.assertRedirects(response, self.upload_url)
        video = Videos.objects.get()
        self.assertEqual(video.nombre, "Video de prueba")
        self.assertEqual(video.descripcion, "Descripción para el catálogo")
        self.assertTrue(video.es_premium)
        self.assertEqual(video.visitas, 0)
        self.assertEqual(video.idioma, language)
        self.assertCountEqual(video.categorias.all(), [category])
        self.assertCountEqual(video.actores.all(), [actor])
        self.assertCountEqual(video.posturas.all(), [position])
        self.assertRegex(video.video.name, r"^upload/videos/[0-9a-f]{32}\.mp4$")
        self.assertRegex(video.miniatura.name, r"^upload/Miniaturas/Premium/[0-9a-f]{32}\.webp$")
        self.assertCountEqual(self.saved_files(), [video.video.name, video.miniatura.name])
        with video.video.open("rb") as uploaded:
            self.assertEqual(uploaded.read(), MP4_HEADER)
        with video.miniatura.open("rb") as uploaded, Image.open(uploaded) as thumbnail:
            self.assertEqual(thumbnail.size, (64, 36))
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user_id, self.publisher.pk)
        self.assertEqual(entry.action_flag, ADDITION)
        self.assertEqual(entry.object_id, str(video.pk))
        self.assertContains(response, "Ver video")
        self.assertContains(response, video.get_absolute_url())

    def test_staff_can_publish_nonpremium_thumbnail_to_its_folder(self):
        self.client.force_login(self.publisher)
        response = self.client.post(self.upload_url, self.upload_data(es_premium=""))

        self.assertRedirects(response, self.upload_url)
        video = Videos.objects.get()
        self.assertFalse(video.es_premium)
        self.assertRegex(video.miniatura.name, r"^upload/Miniaturas/NoPremium/[0-9a-f]{32}\.webp$")

    def test_changing_tier_converts_and_moves_legacy_thumbnail(self):
        self.client.force_login(self.publisher)
        with BytesIO() as thumbnail, Image.new("RGB", (72, 40), "purple") as image:
            image.save(thumbnail, "JPEG")
            old_thumbnail = self.storage.save("upload/photos/legacy.jpg", ContentFile(thumbnail.getvalue()))
        video = Videos.objects.create(
            nombre="Video heredado",
            descripcion="Miniatura antigua",
            miniatura=old_thumbnail,
            video="upload/videos/video.mp4",
            visitas=0,
        )

        response = self.client.post(
            reverse("video_manager_edit", args=[video.pk]),
            {
                "nombre": video.nombre,
                "descripcion": video.descripcion,
                "es_premium": "",
                "idioma": "",
            },
        )

        self.assertRedirects(response, reverse("video_manager"))
        video.refresh_from_db()
        self.assertFalse(video.es_premium)
        self.assertRegex(video.miniatura.name, r"^upload/Miniaturas/NoPremium/[0-9a-f]{32}\.webp$")
        self.assertFalse(self.storage.exists(old_thumbnail))
        with video.miniatura.open("rb") as uploaded, Image.open(uploaded) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (72, 40))

    def test_rejects_invalid_file_contents_without_writes(self):
        self.client.force_login(self.publisher)
        data = self.upload_data(
            video=SimpleUploadedFile("video.mp4", b"invalid video", content_type="video/mp4"),
            miniatura=SimpleUploadedFile("thumbnail.webp", b"invalid image", content_type="image/webp"),
        )
        response = self.client.post(self.upload_url, data)

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(response.context["form"].errors, ["video", "miniatura"])
        self.assert_no_publication()
        self.assertEqual(self.saved_files(), [])

    def test_rejects_jpg_and_png_thumbnails(self):
        self.client.force_login(self.publisher)
        for extension, image_format in (("jpg", "JPEG"), ("png", "PNG")):
            with self.subTest(extension=extension), BytesIO() as thumbnail, Image.new("RGB", (64, 36), "purple") as image:
                image.save(thumbnail, image_format)
                response = self.client.post(
                    self.upload_url,
                    self.upload_data(
                        miniatura=SimpleUploadedFile(
                            f"miniatura.{extension}",
                            thumbnail.getvalue(),
                            content_type=f"image/{extension}",
                        )
                    ),
                )
            self.assertEqual(response.status_code, 200)
            self.assertIn("miniatura", response.context["form"].errors)
            self.assert_no_publication()
            self.assertEqual(self.saved_files(), [])

    def test_storage_error_cleans_only_files_from_the_failed_upload(self):
        self.client.force_login(self.publisher)
        existing_name = self.storage.save("upload/videos/existing.mp4", ContentFile(MP4_HEADER))
        real_save = self.storage.save
        writes = []

        def fail_after_second_write(name, content, *args, **kwargs):
            writes.append(real_save(name, content, *args, **kwargs))
            if len(writes) == 2:
                raise OSError("Simulated storage failure")
            return writes[-1]

        with patch.object(self.storage, "save", side_effect=fail_after_second_write), self.assertLogs():
            response = self.client.post(self.upload_url, self.upload_data())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertEqual(len(writes), 2)
        self.assert_no_publication()
        self.assertEqual(self.saved_files(), [existing_name])
        with self.storage.open(existing_name, "rb") as existing:
            self.assertEqual(existing.read(), MP4_HEADER)

    def test_failed_audit_rolls_back_publication_and_removes_files(self):
        self.client.force_login(self.publisher)
        with (
            patch("app.admin.VideosAdmin.log_addition", side_effect=DatabaseError("Simulated audit failure")),
            self.assertLogs(),
        ):
            response = self.client.post(self.upload_url, self.upload_data())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assert_no_publication()
        self.assertEqual(self.saved_files(), [])
