import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from django.test import SimpleTestCase
from storages.backends.s3 import S3Storage

from .video_durations import (
    VideoDurationError,
    read_stored_video_duration,
    read_uploaded_video_duration,
)


def probe_result(duration, *, video_stream=True):
    streams = [{"codec_type": "video"}] if video_stream else []
    return subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({"format": {"duration": duration}, "streams": streams}).encode(),
    )


class VideoDurationTests(SimpleTestCase):
    @patch("app.video_durations.subprocess.run")
    def test_reads_in_memory_upload_and_restores_it_for_storage(self, run):
        upload = SimpleUploadedFile("sample.mp4", b"sample contents")

        def probe(command, **kwargs):
            self.assertEqual(Path(command[-1]).read_bytes(), b"sample contents")
            self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
            return probe_result("487.800000")

        run.side_effect = probe

        self.assertEqual(read_uploaded_video_duration(upload), 487)
        self.assertEqual(upload.tell(), 0)
        self.assertFalse(Path(run.call_args.args[0][-1]).exists())

    @patch("app.video_durations.subprocess.run", return_value=probe_result("0.480000"))
    def test_reuses_disk_upload_and_displays_at_least_one_second(self, run):
        with TemporaryUploadedFile("sample.mp4", "video/mp4", 6, None) as upload:
            upload.write(b"sample")

            self.assertEqual(read_uploaded_video_duration(upload), 1)
            self.assertEqual(run.call_args.args[0][-1], upload.temporary_file_path())
            self.assertEqual(upload.read(), b"sample")

    @patch("app.video_durations.subprocess.run")
    def test_rejects_unknown_duration_or_missing_video_track(self, run):
        for output in (
            probe_result("N/A"), probe_result("Infinity"), probe_result("0"),
            probe_result("-10"), probe_result("2147483648"), probe_result("5", video_stream=False),
            subprocess.CompletedProcess(args=[], returncode=0, stdout=b"not json"),
        ):
            with self.subTest(output=output.stdout):
                run.return_value = output
                upload = SimpleUploadedFile("sample.mp4", b"sample contents")

                with self.assertRaises(VideoDurationError):
                    read_uploaded_video_duration(upload)
                self.assertEqual(upload.tell(), 0)

    @patch("app.video_durations.subprocess.run", return_value=probe_result("3725.000000"))
    def test_uses_local_storage_path(self, run):
        with TemporaryDirectory() as directory:
            storage = FileSystemStorage(location=directory)
            path = Path(directory) / "sample.mp4"
            path.write_bytes(b"sample contents")

            self.assertEqual(read_stored_video_duration(storage, "sample.mp4"), 3725)
            self.assertEqual(Path(run.call_args.args[0][-1]), path)

    @patch("app.video_durations.subprocess.run")
    def test_uses_seekable_s3_url_and_sanitizes_process_errors(self, run):
        storage = Mock(spec=S3Storage)
        signed_url = "https://test-bucket.s3.amazonaws.com/sample.mp4?X-Amz-Signature=private"
        storage.url.return_value = signed_url

        def probe(command, **kwargs):
            self.assertEqual(command[-1], signed_url)
            self.assertEqual(command[command.index("-seekable") + 1], "1")
            raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

        run.side_effect = probe

        with self.assertRaises(VideoDurationError) as error:
            read_stored_video_duration(storage, "sample.mp4")

        self.assertNotIn("private", str(error.exception))
        self.assertEqual(storage.url.call_args.args, ("sample.mp4",))
        self.assertEqual(storage.url.call_args.kwargs["http_method"], "GET")
        storage.open.assert_not_called()
