from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from .middleware import ContentSecurityPolicyMiddleware
from .play_ads import get_play_ad_layout


def creative(ad_format, url="https://ads.example/creative"):
    return {"enabled": True, "format": ad_format, "url": url}


@override_settings(PLAY_ADS={}, PLAY_AD_PREVIEW=False)
class PlayAdsTests(SimpleTestCase):
    def test_default_has_no_ads(self):
        layout = get_play_ad_layout()
        self.assertIsNone(layout.top_desktop)
        self.assertIsNone(layout.top_mobile)
        self.assertEqual(layout.sidebar, ())
        self.assertEqual(layout.bottom_desktop, ())
        self.assertIsNone(layout.bottom_mobile)
        self.assertEqual(layout.feed, ())
        self.assertEqual(layout.origins, [])

    @override_settings(
        PLAY_ADS={
            "PLAY_TOP_BANNER": {"desktop": creative("728x90"), "mobile": creative("320x100")},
            "PLAY_SIDEBAR_AD_2": {"desktop": creative("300x600"), "mobile": creative("300x250")},
            "PLAY_BOTTOM_AD_1": {"mobile": creative("300x250")},
            "PLAY_BOTTOM_AD_3": {"desktop": creative("300x250"), "mobile": creative("300x250")},
            "PLAY_RECOMMENDED_NATIVE": {"desktop": creative("native"), "mobile": creative("native")},
        }
    )
    def test_configuration_is_independent_by_position_and_device(self):
        layout = get_play_ad_layout()
        self.assertEqual(layout.top_desktop.format, "728x90")
        self.assertEqual(layout.top_mobile.format, "320x100")
        self.assertEqual([slot.format for slot in layout.sidebar], ["300x600"])
        self.assertEqual([slot.position for slot in layout.bottom_desktop], ["PLAY_BOTTOM_AD_3"])
        self.assertEqual(layout.bottom_mobile.position, "PLAY_BOTTOM_AD_1")
        self.assertEqual(
            [(slot.position, slot.device, slot.after_card) for slot in layout.feed],
            [
                ("PLAY_RECOMMENDED_NATIVE", "desktop", 5),
                ("PLAY_RECOMMENDED_NATIVE", "mobile", 5),
                ("PLAY_SIDEBAR_AD_2", "mobile", 8),
            ],
        )

    def test_invalid_variants_do_not_generate_slots_or_origins(self):
        variants = (
            None,
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
            with self.subTest(variant=variant), override_settings(
                PLAY_ADS={"PLAY_TOP_BANNER": {"desktop": variant}}
            ):
                layout = get_play_ad_layout()
                self.assertIsNone(layout.top_desktop)
                self.assertEqual(layout.origins, [])

    @override_settings(DEBUG=True, DEVELOPMENT=True, PLAY_AD_PREVIEW=True)
    def test_preview_only_uses_local_placeholders_and_limits_mobile_volume(self):
        with override_settings(PLAY_ADS={"PLAY_TOP_BANNER": {"desktop": creative("728x90")}}):
            layout = get_play_ad_layout()

        self.assertEqual(layout.top_desktop.format, "728x90")
        self.assertEqual(layout.top_mobile.format, "320x50")
        self.assertEqual(len(layout.sidebar), 3)
        self.assertEqual(len(layout.bottom_desktop), 3)
        self.assertEqual(layout.bottom_mobile.position, "PLAY_BOTTOM_AD_1")
        self.assertEqual([slot.after_card for slot in layout.feed if slot.device == "mobile"], [3, 5])
        self.assertEqual(layout.origins, [])
        markup = render_to_string("partials/ad_slot.html", {"slot": layout.top_desktop})
        self.assertIn("Publicidad", markup)
        self.assertNotIn("data-ad-url", markup)
        self.assertNotIn("ads.example", markup)

    @override_settings(DEBUG=True, DEVELOPMENT=False, PLAY_AD_PREVIEW=True)
    def test_preview_remains_disabled_outside_development(self):
        self.assertIsNone(get_play_ad_layout().top_desktop)

    @override_settings(
        PLAY_ADS={
            "PLAY_TOP_BANNER": {
                "desktop": creative("728x90", "https://Ads.Example:443/creative?one=1&two=2"),
                "mobile": creative("320x100"),
            },
            "PLAY_BOTTOM_AD_1": {"desktop": creative("300x250", "https://banner.example:8443/creative")},
            "PLAY_BOTTOM_AD_2": {"desktop": creative("300x600", "https://unused.example/creative")},
        }
    )
    def test_only_play_allows_exact_origins_and_rendering_defers_iframe_creation(self):
        layout = get_play_ad_layout()
        markup = render_to_string("partials/ad_slot.html", {"slot": layout.top_desktop})
        self.assertIn('data-ad-url="https://Ads.Example:443/creative?one=1&amp;two=2"', markup)
        self.assertIn("data-ad-eager", markup)
        self.assertNotIn("<iframe", markup)

        factory = RequestFactory()
        play = factory.get(reverse("play", args=[1]))
        play.resolver_match = resolve(play.path)
        home = factory.get(reverse("home"))
        home.resolver_match = resolve(home.path)

        middleware = ContentSecurityPolicyMiddleware(lambda request: HttpResponse())
        self.assertIn(
            "frame-src https://ads.example https://banner.example:8443",
            middleware(play)["Content-Security-Policy"].split("; "),
        )
        self.assertIn("frame-src 'none'", middleware(home)["Content-Security-Policy"].split("; "))
        self.assertIn("frame-ancestors 'none'", middleware(play)["Content-Security-Policy"].split("; "))

        not_found = ContentSecurityPolicyMiddleware(lambda request: HttpResponse(status=404))
        self.assertIn("frame-src 'none'", not_found(play)["Content-Security-Policy"].split("; "))
