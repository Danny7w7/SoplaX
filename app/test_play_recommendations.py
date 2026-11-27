from django.test import TestCase
from django.urls import reverse

from .models import Categoria, Videos


class PlayRecommendationsTests(TestCase):
    def create_video(self, *, visitas=0, categorias=(), video="upload/videos/example.mp4"):
        item = Videos.objects.create(nombre="Ejemplo", video=video, visitas=visitas)
        item.categorias.add(*categorias)
        return item

    def recommendations_for(self, video):
        response = self.client.get(reverse("play", args=[video.pk]))
        self.assertEqual(response.status_code, 200)
        return response.context["recommended_videos"]

    def test_prioritizes_shared_categories_then_visits_and_pk(self):
        first_category = Categoria.objects.create(nombre="Grupo A")
        second_category = Categoria.objects.create(nombre="Grupo B")
        other_category = Categoria.objects.create(nombre="Grupo C")
        current = self.create_video(visitas=100, categorias=[first_category, second_category])
        popular = self.create_video(visitas=99)
        one_match = self.create_video(visitas=50, categorias=[first_category, other_category])
        two_matches = self.create_video(visitas=1, categorias=[first_category, second_category])
        tied_match = self.create_video(visitas=50, categorias=[second_category])
        self.create_video(visitas=200, categorias=[first_category, second_category], video="")

        self.assertEqual(
            self.recommendations_for(current),
            [two_matches, one_match, tied_match, popular],
        )

    def test_without_categories_limits_popular_recommendations(self):
        current = self.create_video(visitas=99)
        others = [self.create_video(visitas=visits) for visits in range(14)]

        self.assertEqual(self.recommendations_for(current), list(reversed(others[2:])))
