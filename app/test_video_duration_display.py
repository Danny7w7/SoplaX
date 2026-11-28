from django.test import TestCase
from django.urls import reverse

from .models import Videos


class VideoDurationDisplayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.featured = Videos.objects.create(
            nombre="Video destacado",
            video="upload/videos/featured.mp4",
            miniatura="upload/Miniaturas/Premium/featured.webp",
            visitas=0,
            duracion_segundos=487,
        )
        cls.long_video = Videos.objects.create(
            nombre="Video largo sin miniatura",
            video="upload/videos/long.mp4",
            visitas=0,
            duracion_segundos=3735,
        )
        Videos.objects.create(
            nombre="Video anterior",
            video="upload/videos/legacy.mp4",
            miniatura="upload/Miniaturas/Premium/legacy.webp",
            visitas=0,
        )

    def assert_duration(self, response, element_id, seconds, label):
        self.assertContains(response, f'aria-describedby="{element_id}"')
        self.assertContains(
            response,
            f'<time class="video-duration" id="{element_id}" datetime="PT{seconds}S">'
            f'<span class="visually-hidden">Duración </span>{label}</time>',
            html=True,
            count=1,
        )

    def test_home_displays_durations_in_the_featured_poster_and_cards(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, 'class="video-duration"', count=3)
        self.assert_duration(response, f"featured-video-duration-{self.featured.pk}", 487, "8:07")
        self.assert_duration(response, f"card-video-duration-{self.featured.pk}", 487, "8:07")
        self.assert_duration(response, f"card-video-duration-{self.long_video.pk}", 3735, "1:02:15")

    def test_play_displays_durations_for_recommendations_with_known_lengths(self):
        response = self.client.get(self.featured.get_absolute_url())

        self.assertContains(response, 'class="video-duration"', count=1)
        self.assertContains(response, 'class="video-card__media video-card__media--placeholder"')
        self.assert_duration(response, f"card-video-duration-{self.long_video.pk}", 3735, "1:02:15")
