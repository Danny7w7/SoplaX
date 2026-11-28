from unittest.mock import patch
from xml.etree.ElementTree import fromstring

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Videos


NAMESPACE = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
PUBLIC_ORIGIN = "https://soplax.example"


@override_settings(PUBLIC_BASE_URL=PUBLIC_ORIGIN, ALLOWED_HOSTS=["preview.example", "soplax.example"])
class VideoSitemapTests(TestCase):
    def _get(self, path):
        return self.client.get(path, HTTP_HOST="preview.example")

    def _locations(self, response, root_tag, entry_tag):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"].split(";", 1)[0], "application/xml")
        root = fromstring(response.content)
        self.assertEqual(root.tag, f"{NAMESPACE}{root_tag}")
        return [node.text for node in root.findall(f"{NAMESPACE}{entry_tag}/{NAMESPACE}loc")]

    def test_paginated_sitemaps_use_public_origin_and_playable_video_order(self):
        first = Videos.objects.create(nombre="Primer video", video="first.mp4", visitas=0)
        Videos.objects.create(nombre="Sin archivo", video="", visitas=0)
        second = Videos.objects.create(nombre="Segundo video", video="second.mp4", visitas=0, es_premium=False)
        third = Videos.objects.create(nombre="Tercer video", video="third.mp4", visitas=0)
        first_page = reverse("sitemap_videos", kwargs={"page": 1})
        second_page = reverse("sitemap_videos", kwargs={"page": 2})

        with patch("app.video_sitemaps.VIDEOS_PER_SITEMAP", 2):
            with self.assertNumQueries(1):
                index = self._get(reverse("sitemap_index"))
            with self.assertNumQueries(2):
                first_response = self._get(first_page)
            self.assertEqual(
                self._locations(index, "sitemapindex", "sitemap"),
                [f"{PUBLIC_ORIGIN}{first_page}", f"{PUBLIC_ORIGIN}{second_page}"],
            )
            self.assertEqual(
                self._locations(first_response, "urlset", "url"),
                [f"{PUBLIC_ORIGIN}/", f"{PUBLIC_ORIGIN}{first.get_absolute_url()}",
                 f"{PUBLIC_ORIGIN}{second.get_absolute_url()}"],
            )
            self.assertEqual(
                self._locations(self._get(second_page), "urlset", "url"),
                [f"{PUBLIC_ORIGIN}{third.get_absolute_url()}"],
            )
            self.assertEqual(self._get(reverse("sitemap_videos", kwargs={"page": 3})).status_code, 404)

    def test_empty_catalog_still_lists_home(self):
        first_page = reverse("sitemap_videos", kwargs={"page": 1})
        self.assertEqual(
            self._locations(self._get(reverse("sitemap_index")), "sitemapindex", "sitemap"),
            [f"{PUBLIC_ORIGIN}{first_page}"],
        )
        self.assertEqual(self._locations(self._get(first_page), "urlset", "url"), [f"{PUBLIC_ORIGIN}/"])
        self.assertEqual(self._get(reverse("sitemap_videos", kwargs={"page": 0})).status_code, 404)

    def test_robots_advertises_sitemap_and_allows_old_paths(self):
        response = self._get(reverse("robots_txt"))
        self.assertContains(response, "User-agent: *\nAllow: /\nSitemap: https://soplax.example/sitemap.xml\n")
        self.assertEqual(response["Content-Type"].split(";", 1)[0], "text/plain")
