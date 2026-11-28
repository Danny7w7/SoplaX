from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Videos


PUBLIC_ORIGIN = "https://soplax.example"
HOME_ZONE_FIXTURES = {
    "HOME_TOP_BANNER": {
        "desktop": {"enabled": True, "format": "728x90", "url": "https://top-desktop.example/creative"},
        "mobile": {"enabled": True, "format": "300x250", "url": "https://top-mobile.example/creative"},
    },
    "HOME_FEED_AD": {
        "desktop": {"enabled": True, "format": "300x250", "url": "https://desktop.example/creative"},
        "mobile": {"enabled": True, "format": "300x250", "url": "https://mobile.example/creative"},
    },
}


class CatalogMetadata(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.canonical = None
        self.robots = None
        self.links = {}
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        relation = attributes.get("rel")
        if tag == "link" and relation == "canonical":
            self.canonical = attributes.get("href")
        elif tag == "meta" and attributes.get("name") == "robots":
            self.robots = attributes.get("content")
        elif tag == "a" and relation in ("prev", "next"):
            self.links[relation] = attributes["href"]


@override_settings(PUBLIC_BASE_URL=PUBLIC_ORIGIN, HOME_ADS=HOME_ZONE_FIXTURES, PLAY_AD_PREVIEW=False)
class CatalogPaginationTests(TestCase):
    def create_videos(self, start, stop, prefix="Video de prueba"):
        return Videos.objects.bulk_create([
            Videos(nombre=f"{prefix} {number}", video="upload/videos/example.mp4", visitas=0)
            for number in range(start, stop)
        ])

    def assert_catalog_ads(self, response, *, top_banner, feed_after=None):
        top_marker = 'data-ad-position="HOME_TOP_BANNER"'
        feed_marker = 'data-ad-position="HOME_FEED_AD"'
        origins = []
        html = response.content.decode()
        if top_banner:
            self.assertContains(response, top_marker, count=2)
            self.assertContains(response, "css/components/ad-slots.css")
            self.assertContains(response, "js/ad-slots.js")
            if 'id="hero-title"' in html:
                self.assertLess(html.index('id="hero-title"'), html.index(top_marker))
            self.assertLess(html.index(top_marker), html.index('class="video-card__link"'))
            origins.extend(("https://top-desktop.example", "https://top-mobile.example"))
        else:
            self.assertNotContains(response, top_marker)

        if feed_after is None:
            self.assertNotContains(response, feed_marker)
            self.assertNotContains(response, "ad-grid-item")
        else:
            self.assertContains(response, feed_marker, count=2)
            self.assertContains(response, '<li class="ad-grid-item', count=1)
            before = html.partition(feed_marker)[0]
            self.assertEqual(before.count('class="video-card__link"'), feed_after)
            origins.extend(("https://desktop.example", "https://mobile.example"))

        self.assertNotContains(response, "<iframe")
        frame_sources = " ".join(sorted(origins)) or "'none'"
        self.assertIn(
            f"frame-src {frame_sources}",
            response["Content-Security-Policy"].split("; "),
        )

    def test_catalog_ads_follow_the_number_of_videos_actually_displayed(self):
        home = reverse("home")
        previous_size = 0
        for size, ad_after in ((0, None), (1, None), (5, None), (6, 6), (9, 6), (24, 6), (25, 6)):
            with self.subTest(size=size):
                self.create_videos(previous_size, size)
                response = self.client.get(home)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context["videos"]), min(size, 24))
                self.assert_catalog_ads(response, top_banner=size > 0, feed_after=ad_after)
            previous_size = size

        last = self.client.get(home, {"page": 2})
        self.assertEqual(last.status_code, 200)
        self.assertEqual(len(last.context["videos"]), 1)
        self.assert_catalog_ads(last, top_banner=True)

    def test_all_thousand_videos_reachable_through_rendered_links(self):
        videos = self.create_videos(0, 1000)
        expected_ids = [video.pk for video in videos]
        seen_ids = []
        home = reverse("home")
        path = home
        for number in range(1, 43):
            with self.subTest(page=number):
                with self.assertNumQueries(2):
                    response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                metadata = CatalogMetadata(response)
                self.assertEqual(metadata.canonical, f"{PUBLIC_ORIGIN}{path}")
                self.assertIsNone(metadata.robots)
                page_ids = [video.pk for video in response.context["videos"]]
                self.assertEqual(len(page_ids), 24 if number < 42 else 16)
                seen_ids.extend(page_ids)
                self.assert_catalog_ads(response, top_banner=True, feed_after=6)
                if number > 1:
                    previous = home if number == 2 else f"{home}?page={number - 1}"
                    self.assertEqual(metadata.links.get("prev"), previous)
                if number < 42:
                    self.assertEqual(metadata.links.get("next"), f"{home}?page={number + 1}")
                    path = metadata.links["next"]
                else:
                    self.assertNotIn("next", metadata.links)
        self.assertEqual(seen_ids, expected_ids)

    def test_catalog_canonical_normalizes_first_page_and_invalid_pages_are_404(self):
        self.create_videos(0, 25)
        home = reverse("home")
        duplicate = self.client.get(home, {"page": 1, "search": ""})
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(CatalogMetadata(duplicate).canonical, f"{PUBLIC_ORIGIN}{home}")
        for page in ("0", "-1", "abc", "3"):
            with self.subTest(page=page):
                response = self.client.get(home, {"page": page})
                self.assertEqual(response.status_code, 404)
                self.assertIn("frame-src 'none'", response["Content-Security-Policy"].split("; "))

    def test_search_retains_query_in_pagination_and_omits_ads_and_indexing(self):
        self.create_videos(0, 25, prefix="Clip & mar")
        query = "Clip & mar"
        home = reverse("home")
        result = self.client.get(home, {"search": query})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.context["videos"]), 24)
        self.assert_catalog_ads(result, top_banner=False)
        metadata = CatalogMetadata(result)
        self.assertIsNone(metadata.canonical)
        self.assertIn("noindex", metadata.robots)
        next_url = metadata.links["next"]
        self.assertEqual(parse_qs(urlsplit(next_url).query), {"search": [query], "page": ["2"]})
        second = self.client.get(next_url)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.context["videos"]), 1)
        self.assert_catalog_ads(second, top_banner=False)
        self.assertIn("noindex", CatalogMetadata(second).robots)
