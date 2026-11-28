from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Videos


@override_settings(PUBLIC_BASE_URL="https://soplax.example")
class VideoURLTests(TestCase):
    def create_video(self, title, source="upload/videos/example.mp4"):
        return Videos.objects.create(nombre=title, video=source, visitas=0)

    def test_descriptive_urls_distinguish_duplicate_titles_and_are_used_by_cards(self):
        first = self.create_video("Acción en Bogotá_2026")
        second = self.create_video(first.nombre)
        first_path = f"/videos/accion-en-bogota-2026-{first.pk}/"
        second_path = f"/videos/accion-en-bogota-2026-{second.pk}/"
        self.assertEqual(first.get_absolute_url(), first_path)
        self.assertEqual(second.get_absolute_url(), second_path)

        catalog = self.client.get(reverse("home"))
        for path in (first_path, second_path):
            self.assertContains(catalog, f'href="{path}"')
        self.assertNotContains(catalog, 'href="/play/')

        playback = self.client.get(first_path)
        self.assertContains(playback, f'href="{second_path}"')
        self.assertContains(playback, f'<link rel="canonical" href="https://soplax.example{first_path}">', count=1)

    def test_title_with_no_slug_uses_the_video_id(self):
        video = self.create_video("🎬")
        self.assertEqual(video.get_absolute_url(), f"/videos/video-{video.pk}/")
        self.assertEqual(self.client.get(video.get_absolute_url()).status_code, 200)

    def test_title_changes_and_url_variants_redirect_directly_without_counting_visits(self):
        video = self.create_video("Título anterior")
        old_path = video.get_absolute_url()
        video.nombre = "Título corregido"
        video.save(update_fields=["nombre"])
        canonical = video.get_absolute_url()

        variants = (
            reverse("play", args=[video.pk]),
            f"/play/{video.pk}",
            old_path,
            old_path.rstrip("/"),
            canonical.rstrip("/"),
            f"/videos/TITULO_Corregido-{video.pk}/",
            f"/videos/titulo-corregido-0{video.pk}/",
        )
        for path in variants:
            with self.subTest(path=path):
                self.assertRedirects(self.client.get(path), canonical, status_code=301, fetch_redirect_response=False)
        self.assertEqual(self.client.head(canonical).status_code, 200)
        video.refresh_from_db()
        self.assertEqual(video.visitas, 0)

    def test_following_legacy_link_keeps_campaign_parameters_and_counts_one_visit(self):
        video = self.create_video("Ejemplo")
        canonical = video.get_absolute_url()
        query = "utm_source=catalogo&utm_campaign=uno&utm_campaign=dos"
        response = self.client.get(f"/play/{video.pk}?{query}", follow=True)
        self.assertEqual(response.redirect_chain, [(f"{canonical}?{query}", 301)])
        self.assertContains(response, f'<link rel="canonical" href="https://soplax.example{canonical}">', count=1)
        video.refresh_from_db()
        self.assertEqual(video.visitas, 1)

    def test_invalid_and_unplayable_videos_return_not_found(self):
        video = self.create_video("Sin archivo", source="")
        for path in (video.get_absolute_url(), reverse("play", args=[video.pk]), "/videos/inexistente-0/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
