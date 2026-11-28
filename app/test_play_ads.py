from urllib.parse import parse_qs, urlsplit

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from project.ad_zones import DEFAULT_HOME_ADS, DEFAULT_PLAY_ADS

from .models import Videos
from .play_ads import get_home_ad_layout, get_play_ad_layout


def creative(ad_format, url="https://ads.example/creative"):
    return {"enabled": True, "format": ad_format, "url": url}


PLAY_ZONE_FIXTURES = {
    "PLAY_TOP_BANNER": {
        "desktop": creative("728x90", "https://Ads.Example:443/creative?one=1&two=2"),
        "mobile": creative("320x100", "https://unused.example/mobile-top"),
    },
    "PLAY_SIDEBAR_AD_1": {
        "desktop": creative("300x500", "https://sidebar.example/creative"),
        "mobile": creative("300x250", "https://banner.example:8443/creative"),
    },
    "PLAY_SIDEBAR_AD_2": {"desktop": creative("300x600", "https://unused.example/extra-sidebar")},
    "PLAY_BOTTOM_AD_1": {
        "desktop": creative("300x250", "https://bottom-desktop.example/creative"),
        "mobile": creative("300x250", "https://bottom-mobile.example/creative"),
    },
    "PLAY_RECOMMENDED_NATIVE": {"mobile": creative("native", "https://unused.example/native")},
}


@override_settings(HOME_ADS={}, PLAY_ADS={}, PLAY_AD_PREVIEW=False)
class AdLayoutsTests(SimpleTestCase):
    def test_empty_configuration_has_no_ads(self):
        for layout in (get_play_ad_layout(12), get_home_ad_layout(24)):
            self.assertIsNone(layout.watch_banner)
            self.assertIsNone(layout.watch_sidebar)
            self.assertIsNone(layout.feed_after)
            self.assertEqual(layout.feed_slots, ())
            self.assertEqual(layout.top_slots, ())
            self.assertEqual(layout.bottom_slots, ())
            self.assertEqual(layout.origins, ())

    @override_settings(PLAY_ADS=PLAY_ZONE_FIXTURES)
    def test_play_uses_three_desktop_zones_and_two_mobile_zones(self):
        layout = get_play_ad_layout(9)
        self.assertEqual(layout.watch_banner.position, "PLAY_TOP_BANNER")
        self.assertEqual(layout.watch_banner.device, "desktop")
        self.assertEqual(layout.watch_banner.format, "728x90")
        self.assertEqual(layout.watch_sidebar.position, "PLAY_SIDEBAR_AD_1")
        self.assertEqual(layout.watch_sidebar.device, "desktop")
        self.assertEqual((layout.watch_sidebar.width, layout.watch_sidebar.height), (300, 500))
        self.assertEqual(layout.feed_after, 3)
        self.assertEqual(
            [(slot.position, slot.device, slot.format) for slot in layout.feed_slots],
            [("PLAY_SIDEBAR_AD_1", "mobile", "300x250")],
        )
        self.assertEqual(
            [(slot.position, slot.device, slot.format) for slot in layout.bottom_slots],
            [("PLAY_BOTTOM_AD_1", "desktop", "300x250"), ("PLAY_BOTTOM_AD_1", "mobile", "300x250")],
        )
        self.assertEqual(
            layout.origins,
            (
                "https://ads.example",
                "https://banner.example:8443",
                "https://bottom-desktop.example",
                "https://bottom-mobile.example",
                "https://sidebar.example",
            ),
        )

    @override_settings(PLAY_ADS={"PLAY_TOP_BANNER": {"desktop": creative("970x90")}})
    def test_existing_wider_desktop_format_remains_supported(self):
        layout = get_play_ad_layout(0)
        self.assertEqual(layout.watch_banner.format, "970x90")
        self.assertIsNone(layout.watch_sidebar)
        self.assertIsNone(layout.feed_after)

    @override_settings(
        HOME_ADS={
            "HOME_TOP_BANNER": {"desktop": creative("728x90"), "mobile": creative("300x250")},
            "HOME_FEED_AD": {"desktop": creative("300x250"), "mobile": creative("300x250")},
        },
    )
    def test_catalog_has_top_and_feed_positions_with_device_variants(self):
        layout = get_home_ad_layout(24)
        self.assertIsNone(layout.watch_banner)
        self.assertIsNone(layout.watch_sidebar)
        self.assertEqual(layout.feed_after, 6)
        self.assertEqual({slot.device for slot in layout.feed_slots}, {"desktop", "mobile"})
        self.assertEqual({slot.position for slot in layout.feed_slots}, {"HOME_FEED_AD"})
        self.assertEqual({slot.device for slot in layout.top_slots}, {"desktop", "mobile"})
        self.assertEqual({slot.position for slot in layout.top_slots}, {"HOME_TOP_BANNER"})
        self.assertEqual(layout.origins, ("https://ads.example",))

    @override_settings(HOME_ADS=DEFAULT_HOME_ADS, PLAY_ADS=DEFAULT_PLAY_ADS)
    def test_default_layout_selects_all_nine_supplied_exoclick_zones(self):
        play = get_play_ad_layout(9)
        home = get_home_ad_layout(24)
        slots = (
            play.watch_banner, play.watch_sidebar, *play.bottom_slots, *play.feed_slots,
            *home.top_slots, *home.feed_slots,
        )
        self.assertEqual(len(slots), 9)
        self.assertEqual(
            {
                (slot.position, slot.device): (slot.format, parse_qs(urlsplit(slot.url).query)["idzone"][0])
                for slot in slots
            },
            {
                ("PLAY_TOP_BANNER", "desktop"): ("728x90", "6112582"),
                ("PLAY_SIDEBAR_AD_1", "desktop"): ("300x500", "6112600"),
                ("PLAY_BOTTOM_AD_1", "desktop"): ("300x250", "6112602"),
                ("PLAY_BOTTOM_AD_1", "mobile"): ("300x250", "6112604"),
                ("PLAY_SIDEBAR_AD_1", "mobile"): ("300x250", "6112606"),
                ("HOME_TOP_BANNER", "desktop"): ("728x90", "6112656"),
                ("HOME_TOP_BANNER", "mobile"): ("300x250", "6112658"),
                ("HOME_FEED_AD", "desktop"): ("300x250", "6112660"),
                ("HOME_FEED_AD", "mobile"): ("300x250", "6112662"),
            },
        )
        self.assertEqual(play.origins, ("https://a.magsrv.com",))
        self.assertEqual(home.origins, play.origins)

    def test_invalid_variants_do_not_generate_slots_or_origins(self):
        variants = (
            None,
            {"enabled": False, "format": "728x90", "url": "https://ads.example/creative"},
            {"enabled": "true", "format": "728x90", "url": "https://ads.example/creative"},
            creative("320x50"),
            creative("728x90", "http://ads.example/creative"),
            creative("728x90", "//ads.example/creative"),
            creative("728x90", "https://user:pass@ads.example/creative"),
            creative("728x90", "https://*.example/creative"),
            creative("728x90", "https://ads.example/creative\n"),
            creative("728x90", "https://ads.example\\redirect"),
            creative("728x90", "https://127.0.0.1/creative"),
            creative("728x90", "https://ads.example:65536/creative"),
        )
        for variant in variants:
            home_variant = variant
            if isinstance(variant, dict) and variant.get("format") == "728x90":
                home_variant = {**variant, "format": "300x250"}
            with self.subTest(variant=variant), override_settings(
                PLAY_ADS={"PLAY_TOP_BANNER": {"desktop": variant}},
                HOME_ADS={"HOME_FEED_AD": {"desktop": home_variant, "mobile": home_variant}},
            ):
                play = get_play_ad_layout(12)
                home = get_home_ad_layout(24)
                self.assertIsNone(play.watch_banner)
                self.assertEqual(play.origins, ())
                self.assertIsNone(home.feed_after)
                self.assertEqual(home.feed_slots, ())
                self.assertEqual(home.origins, ())

    @override_settings(DEBUG=True, DEVELOPMENT=True, PLAY_AD_PREVIEW=True, PLAY_ADS=PLAY_ZONE_FIXTURES)
    def test_local_preview_respects_placement_and_does_not_fetch_play_creatives(self):
        layout = get_play_ad_layout(9)
        self.assertEqual(layout.watch_banner.format, "728x90")
        self.assertEqual(layout.watch_sidebar.format, "300x500")
        self.assertEqual(layout.feed_after, 3)
        self.assertEqual(len(layout.bottom_slots), 2)
        self.assertEqual([slot.device for slot in layout.feed_slots], ["mobile"])
        self.assertEqual(layout.origins, ())
        markup = render_to_string("partials/ad_slot.html", {"slot": layout.watch_banner})
        self.assertIn("Publicidad", markup)
        self.assertNotIn("data-ad-url", markup)
        self.assertNotIn("ads.example", markup)

    @override_settings(
        DEBUG=True,
        DEVELOPMENT=True,
        PLAY_AD_PREVIEW=True,
        HOME_ADS={"HOME_FEED_AD": {"desktop": creative("300x250")}},
    )
    def test_home_preview_preserves_configured_zone_and_previews_missing_variant(self):
        self.assertIsNone(get_home_ad_layout(5).feed_after)
        layout = get_home_ad_layout(6)
        self.assertEqual(layout.feed_after, 6)
        self.assertEqual(
            {slot.device: slot.url for slot in layout.feed_slots},
            {"desktop": "https://ads.example/creative", "mobile": ""},
        )
        self.assertEqual(layout.origins, ("https://ads.example",))

    @override_settings(
        DEBUG=True,
        DEVELOPMENT=True,
        PLAY_AD_PREVIEW=True,
        HOME_ADS={"HOME_FEED_AD": {"desktop": {"enabled": False}}},
    )
    def test_explicitly_disabled_variant_is_not_previewed(self):
        layout = get_home_ad_layout(6)
        self.assertEqual([slot.device for slot in layout.feed_slots], ["mobile"])

    @override_settings(DEBUG=True, DEVELOPMENT=False, PLAY_AD_PREVIEW=True)
    def test_preview_remains_disabled_outside_development(self):
        self.assertIsNone(get_play_ad_layout(12).watch_banner)
        self.assertEqual(get_home_ad_layout(24).feed_slots, ())


@override_settings(PLAY_ADS=PLAY_ZONE_FIXTURES, PLAY_AD_PREVIEW=False)
class PlayAdPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.video = Videos.objects.create(
            nombre="Video de prueba",
            descripcion="Descripción de prueba del video",
            video="upload/videos/example.mp4",
            visitas=0,
        )
        Videos.objects.bulk_create([
            Videos(nombre=f"Video relacionado {index}", video="upload/videos/example.mp4", visitas=0)
            for index in range(2)
        ])

    def test_play_with_few_recommendations_omits_recommended_ad_and_its_origin(self):
        response = self.client.get(self.video.get_absolute_url())
        self.assertContains(response, 'data-ad-position="PLAY_TOP_BANNER"', count=1)
        self.assertContains(response, 'data-ad-position="PLAY_SIDEBAR_AD_1" data-ad-device="desktop"', count=1)
        self.assertContains(response, 'data-ad-position="PLAY_BOTTOM_AD_1"', count=2)
        self.assertNotContains(response, "ad-grid-item")
        self.assertIn(
            "frame-src https://ads.example https://bottom-desktop.example https://bottom-mobile.example https://sidebar.example",
            response["Content-Security-Policy"].split("; "),
        )

    @override_settings(PLAY_ADS={"PLAY_TOP_BANNER": {"desktop": creative("728x90")}})
    def test_play_has_no_sidebar_column_without_a_sidebar_zone(self):
        response = self.client.get(self.video.get_absolute_url())
        self.assertContains(response, 'data-ad-position="PLAY_TOP_BANNER"', count=1)
        self.assertNotContains(response, "play-page--sidebar")
        self.assertNotContains(response, 'class="play-sidebar')

    def test_play_places_banners_around_player_and_between_recommendations(self):
        Videos.objects.bulk_create([
            Videos(nombre=f"Otro video relacionado {index}", video="upload/videos/example.mp4", visitas=0)
            for index in range(7)
        ])
        response = self.client.get(self.video.get_absolute_url())
        self.assertContains(response, 'data-ad-position="PLAY_TOP_BANNER"', count=1)
        self.assertContains(response, 'data-ad-position="PLAY_SIDEBAR_AD_1"', count=2)
        self.assertContains(response, 'data-ad-position="PLAY_BOTTOM_AD_1"', count=2)
        self.assertContains(response, '<li class="ad-grid-item', count=1)
        self.assertContains(response, 'data-ad-url="https://Ads.Example:443/creative?one=1&amp;two=2"')
        self.assertNotContains(response, "unused.example")
        self.assertNotContains(response, "<iframe")
        html = response.content.decode()
        player = html.index("<video")
        description = html.index("Descripción de prueba del video", player)
        top = html.index('data-ad-position="PLAY_TOP_BANNER"')
        sidebar = html.index('data-ad-position="PLAY_SIDEBAR_AD_1" data-ad-device="desktop"')
        bottom = html.index('data-ad-position="PLAY_BOTTOM_AD_1"')
        recommendations = html.index('id="recommended-title"')
        mobile = html.index('data-ad-position="PLAY_SIDEBAR_AD_1" data-ad-device="mobile"')
        self.assertLess(html.index("data-site-header"), top)
        self.assertLess(top, player)
        self.assertLess(player, description)
        self.assertLess(description, sidebar)
        self.assertLess(sidebar, recommendations)
        self.assertLess(description, bottom)
        self.assertLess(bottom, recommendations)
        self.assertLess(recommendations, mobile)
        self.assertEqual(html[recommendations:mobile].count('class="video-card__link"'), 3)
        self.assertEqual(html[mobile:].count('class="video-card__link"'), 6)
        self.assertIn(
            "frame-src https://ads.example https://banner.example:8443 https://bottom-desktop.example "
            "https://bottom-mobile.example https://sidebar.example",
            response["Content-Security-Policy"].split("; "),
        )
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"].split("; "))

    def test_ad_origins_do_not_leak_to_redirects_errors_or_other_routes(self):
        responses = (
            self.client.get(reverse("play", args=[self.video.pk])),
            self.client.get(reverse("video_detail", args=["inexistente", self.video.pk + 100])),
            self.client.get(reverse("login")),
        )
        self.assertEqual([response.status_code for response in responses], [301, 404, 200])
        for response in responses:
            self.assertIn("frame-src 'none'", response["Content-Security-Policy"].split("; "))
