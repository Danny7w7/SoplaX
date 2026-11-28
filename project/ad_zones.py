"""Public ExoClick zones used when no environment override is supplied."""


def _banner(zone_id, ad_format):
    return {
        "enabled": True,
        "format": ad_format,
        "url": f"https://a.magsrv.com/iframe.php?idzone={zone_id}&size={ad_format}",
    }


DEFAULT_HOME_ADS = {
    "HOME_TOP_BANNER": {
        "desktop": _banner(6112656, "728x90"),
        "mobile": _banner(6112658, "300x250"),
    },
    "HOME_FEED_AD": {
        "desktop": _banner(6112660, "300x250"),
        "mobile": _banner(6112662, "300x250"),
    },
}

DEFAULT_PLAY_ADS = {
    "PLAY_TOP_BANNER": {"desktop": _banner(6112582, "728x90")},
    "PLAY_SIDEBAR_AD_1": {
        "desktop": _banner(6112600, "300x500"),
        "mobile": _banner(6112606, "300x250"),
    },
    "PLAY_BOTTOM_AD_1": {
        "desktop": _banner(6112602, "300x250"),
        "mobile": _banner(6112604, "300x250"),
    },
}
