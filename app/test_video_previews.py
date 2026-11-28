import subprocess
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Usuario, Videos
from .video_durations import VideoDurationError
from .video_previews import (
    VideoPreviewError,
    build_preview,
    generate_video_preview,
    preview_clips,
    preview_command,
)


MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isommp42"
PREVIEW_BYTES = b"preview mp4"


def write_preview(source, duration, output_path, *, remote=False):
    Path(output_path).write_bytes(PREVIEW_BYTES)


class PreviewCommandTests(SimpleTestCase):
    def test_short_videos_use_one_clip_of_at_most_ten_seconds(self):
        self.assertEqual(preview_clips(8), [(0, 8)])
        self.assertEqual(preview_clips(11), [(0, 10)])

    def test_long_videos_use_five_two_second_clips_inside_the_video(self):
        self.assertEqual(preview_clips(100), [(10.0, 2), (30.0, 2), (50.0, 2), (70.0, 2), (90.0, 2)])
        self.assertEqual(preview_clips(12)[-1], (10, 2))
        for start, length in preview_clips(3725):
            self.assertLessEqual(start + length, 3725)

    def test_command_restricts_inputs_and_writes_a_silent_streamable_mp4(self):
        command = preview_command("/videos/a.mp4", preview_clips(100), "/tmp/out.mp4")

        self.assertEqual(command.count("-i"), 5)
        self.assertEqual(command.count("-protocol_whitelist"), 5)
        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
        self.assertIn("concat=n=5:v=1:a=0[preview]", command[command.index("-filter_complex") + 1])
        self.assertIn("scale=-2:360", command[command.index("-filter_complex") + 1])
        self.assertIn("-an", command)
        self.assertEqual(command[command.index("-movflags") + 1], "+faststart")
        self.assertEqual(command[-1], "/tmp/out.mp4")

    def test_remote_sources_only_allow_https(self):
        command = preview_command("https://bucket.example/a.mp4", [(0, 5)], "/tmp/out.mp4", remote=True)

        self.assertEqual(command[command.index("-protocol_whitelist") + 1], "https,tls,tcp")
        self.assertEqual(command[command.index("-tls_verify") + 1], "1")

    @patch("app.video_previews.read_local_video_duration", return_value=10)
    @patch("app.video_previews.subprocess.run")
    def test_build_validates_the_generated_file(self, run, read_duration):
        build_preview("/videos/a.mp4", 100, "/tmp/out.mp4")

        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["timeout"], 240)
        read_duration.assert_called_once_with("/tmp/out.mp4")

    def test_build_errors_never_include_ffmpeg_output(self):
        secret_url = "https://bucket.example/a.mp4?X-Amz-Signature=secret"
        for side_effect, message in (
            (FileNotFoundError(), "ffmpeg no está disponible"),
            (subprocess.TimeoutExpired("ffmpeg", 240), "Se agotó el tiempo"),
            (subprocess.CalledProcessError(1, "ffmpeg", stderr=secret_url.encode()), "No se pudo crear"),
        ):
            with self.subTest(message=message), patch("app.video_previews.subprocess.run", side_effect=side_effect):
                with self.assertRaisesMessage(VideoPreviewError, message) as raised:
                    build_preview(secret_url, 100, "/tmp/out.mp4", remote=True)
                self.assertNotIn("secret", str(raised.exception))

    @patch("app.video_previews.read_local_video_duration", side_effect=VideoDurationError("x"))
    @patch("app.video_previews.subprocess.run")
    def test_build_rejects_an_unreadable_result(self, run, read_duration):
        with self.assertRaisesMessage(VideoPreviewError, "no es un MP4 válido"):
            build_preview("/videos/a.mp4", 100, "/tmp/out.mp4")


class PreviewStorageTestCase(TestCase):
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

    def create_video(self, **fields):
        return Videos.objects.create(**{
            "nombre": "Video de prueba",
            "descripcion": "Descripción",
            "miniatura": "upload/Miniaturas/Premium/test.webp",
            "video": self.storage.save("upload/videos/video.mp4", ContentFile(MP4_HEADER)),
            "duracion_segundos": 100,
            "visitas": 0,
            **fields,
        })

    def saved_previews(self):
        folder = self.media_root / "upload" / "previews"
        return sorted(path.name for path in folder.glob("*")) if folder.exists() else []


@patch("app.video_previews.build_preview", side_effect=write_preview)
class GenerateVideoPreviewTests(PreviewStorageTestCase):
    def test_stores_the_preview_and_replaces_the_previous_one(self, build):
        old_preview = self.storage.save("upload/previews/old.mp4", ContentFile(b"old"))
        video = self.create_video(preview=old_preview)

        name = generate_video_preview(video.pk, video.video.name)

        video.refresh_from_db()
        self.assertEqual(video.preview.name, name)
        self.assertRegex(name, r"^upload/previews/[0-9a-f]{32}\.mp4$")
        with video.preview.open("rb") as preview:
            self.assertEqual(preview.read(), PREVIEW_BYTES)
        self.assertFalse(self.storage.exists(old_preview))
        self.assertEqual(build.call_args.args[1], 100)
        self.assertEqual(build.call_args.args[0], self.storage.path(video.video.name))

    @patch("app.video_previews.read_stored_video_duration", return_value=487)
    def test_reads_and_saves_a_missing_duration(self, read_duration, build):
        video = self.create_video(duracion_segundos=None)

        generate_video_preview(video.pk, video.video.name)

        video.refresh_from_db()
        self.assertEqual(video.duracion_segundos, 487)
        self.assertEqual(build.call_args.args[1], 487)

    def test_skips_a_video_whose_file_changed_before_starting(self, build):
        video = self.create_video()

        self.assertIsNone(generate_video_preview(video.pk, "upload/videos/other.mp4"))
        build.assert_not_called()

    def test_discards_the_preview_when_the_video_changes_while_generating(self, build):
        video = self.create_video()

        def replace_video_then_write(*args, **kwargs):
            Videos.objects.filter(pk=video.pk).update(video="upload/videos/replacement.mp4")
            write_preview(*args, **kwargs)

        build.side_effect = replace_video_then_write

        self.assertIsNone(generate_video_preview(video.pk, video.video.name))
        video.refresh_from_db()
        self.assertEqual(video.preview.name, "")
        self.assertEqual(self.saved_previews(), [])

    def test_failed_generation_keeps_the_current_preview(self, build):
        old_preview = self.storage.save("upload/previews/old.mp4", ContentFile(b"old"))
        video = self.create_video(preview=old_preview)
        build.side_effect = VideoPreviewError("No se pudo crear la vista previa del MP4.")

        with self.assertRaises(VideoPreviewError):
            generate_video_preview(video.pk, video.video.name)

        video.refresh_from_db()
        self.assertEqual(video.preview.name, old_preview)
        self.assertTrue(self.storage.exists(old_preview))


class PreviewSchedulingTests(PreviewStorageTestCase):
    @classmethod
    def setUpTestData(cls):
        permissions = Permission.objects.filter(
            content_type__app_label="app", codename__in=["add_videos", "change_videos", "delete_videos", "view_videos"],
        )
        cls.publisher = Usuario.objects.create_user(username="publisher", is_staff=True)
        cls.publisher.user_permissions.add(*permissions)

    def setUp(self):
        super().setUp()
        self.enterContext(patch("app.video_uploads.read_uploaded_video_duration", return_value=487))
        self.generate = self.enterContext(patch("app.video_previews.generate_video_preview"))
        self.client.force_login(self.publisher)

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

    def test_new_uploads_schedule_a_preview_after_commit(self):
        for route in ("video_manager_add", "admin:app_videos_add"):
            with self.subTest(route=route):
                self.generate.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(reverse(route), self.upload_data())
                video = Videos.objects.latest("pk")
                self.generate.assert_called_once_with(video.pk, video.video.name)

    @override_settings(DEVELOPMENT=False)
    def test_production_enqueues_the_preview_job(self):
        with patch("django_rq.get_queue") as get_queue, self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("video_manager_add"), self.upload_data())

        video = Videos.objects.get()
        get_queue.assert_called_once_with("video_previews", commit_mode="auto")
        enqueue = get_queue.return_value.enqueue
        self.assertEqual(enqueue.call_args.args[1:], (video.pk, video.video.name))
        self.assertEqual(enqueue.call_args.kwargs["job_timeout"], 360)
        self.generate.assert_not_called()

    def test_generation_failure_keeps_the_upload(self):
        self.generate.side_effect = VideoPreviewError("No se pudo crear la vista previa del MP4.")
        with self.assertLogs("app.video_previews", "WARNING"), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("video_manager_add"), self.upload_data())

        self.assertRedirects(response, reverse("video_manager"))
        video = Videos.objects.get()
        self.assertTrue(self.storage.exists(video.video.name))

    def test_replacing_the_video_clears_and_reschedules_the_preview(self):
        for route in ("video_manager_edit", "admin:app_videos_change"):
            with self.subTest(route=route):
                self.generate.reset_mock()
                old_preview = self.storage.save("upload/previews/old.mp4", ContentFile(b"old"))
                video = self.create_video(preview=old_preview)
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(reverse(route, args=[video.pk]), {
                        "nombre": video.nombre,
                        "descripcion": video.descripcion,
                        "es_premium": "on",
                        "video": SimpleUploadedFile("replacement.mp4", MP4_HEADER, content_type="video/mp4"),
                        "visitas": video.visitas,
                        "_save": "Guardar",
                    })

                video.refresh_from_db()
                self.assertEqual(video.preview.name, "")
                self.assertFalse(self.storage.exists(old_preview))
                self.generate.assert_called_once_with(video.pk, video.video.name)

    def test_metadata_edits_keep_the_preview(self):
        preview = self.storage.save("upload/previews/current.mp4", ContentFile(b"current"))
        video = self.create_video(preview=preview)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("video_manager_edit", args=[video.pk]), {
                "nombre": video.nombre,
                "descripcion": "Descripción nueva",
                "es_premium": "on",
            })

        video.refresh_from_db()
        self.assertEqual(video.descripcion, "Descripción nueva")
        self.assertEqual(video.preview.name, preview)
        self.assertTrue(self.storage.exists(preview))
        self.generate.assert_not_called()

    def test_deleting_a_video_removes_its_preview(self):
        preview = self.storage.save("upload/previews/current.mp4", ContentFile(b"current"))
        video = self.create_video(preview=preview)

        self.client.post(reverse("video_manager_delete", args=[video.pk]))

        self.assertFalse(Videos.objects.exists())
        self.assertFalse(self.storage.exists(preview))


class PreviewMarkupTests(PreviewStorageTestCase):
    def test_cards_expose_the_preview_only_when_it_exists(self):
        with_preview = self.create_video(nombre="Con vista previa", preview="upload/previews/a.mp4")
        self.create_video(nombre="Sin vista previa")

        response = self.client.get(reverse("home"))

        self.assertContains(response, 'data-preview-src="/media/upload/previews/a.mp4"', count=2)
        self.assertEqual(response.content.decode().count("data-preview-src"), 2)
        recommendations = self.client.get(Videos.objects.exclude(pk=with_preview.pk).get().get_absolute_url())
        self.assertContains(recommendations, 'data-preview-src="/media/upload/previews/a.mp4"', count=1)


@patch("app.management.commands.generar_previews_videos.read_stored_video_duration", return_value=487)
@patch("app.video_previews.build_preview", side_effect=write_preview)
class GenerarPreviewsVideosTests(PreviewStorageTestCase):
    def run_command(self, *args):
        stdout = StringIO()
        call_command("generar_previews_videos", *args, stdout=stdout, stderr=StringIO())
        return stdout.getvalue()

    def test_dry_run_reports_the_plan_without_writing(self, build, read_duration):
        video = self.create_video(duracion_segundos=None)

        output = self.run_command()

        self.assertIn(f"Video {video.pk}: vista previa pendiente → 5 tramos, 10 s (video de 487 s).", output)
        self.assertIn("Simulación: 1 vistas previas por crear", output)
        build.assert_not_called()
        video.refresh_from_db()
        self.assertEqual(video.preview.name, "")
        self.assertIsNone(video.duracion_segundos)

    def test_apply_creates_pending_previews_once(self, build, read_duration):
        videos = [self.create_video(), self.create_video()]
        self.create_video(video="")

        output = self.run_command("--aplicar")

        self.assertIn("Aplicado: 2 vistas previas creadas", output)
        self.assertIn("Videos sin archivo: 1", output)
        for video in videos:
            video.refresh_from_db()
            self.assertTrue(video.preview.name)
        second = self.run_command("--aplicar")
        self.assertIn("Aplicado: 0 vistas previas creadas", second)
        self.assertIn("Vistas previas ya registradas: 2", second)

    def test_limit_processes_only_the_requested_amount(self, build, read_duration):
        self.create_video()
        self.create_video()

        self.assertIn("Aplicado: 1 vistas previas creadas", self.run_command("--aplicar", "--limite", "1"))

    def test_failures_are_reported_and_stop_with_an_error(self, build, read_duration):
        ok, broken = self.create_video(), self.create_video()

        def fail_for_second_video(source, *args, **kwargs):
            if source == self.storage.path(broken.video.name):
                raise VideoPreviewError("No se pudo crear la vista previa del MP4.")
            write_preview(source, *args, **kwargs)

        build.side_effect = fail_for_second_video

        with self.assertRaisesMessage(CommandError, "Algunos videos fallaron"):
            self.run_command("--aplicar")

        ok.refresh_from_db()
        broken.refresh_from_db()
        self.assertTrue(ok.preview.name)
        self.assertEqual(broken.preview.name, "")
