import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


@dataclass(frozen=True)
class Placement:
    position: str
    device: str
    formats: tuple[str, ...]


@dataclass(frozen=True)
class AdSlot:
    position: str
    device: str
    format: str
    url: str = ""
    origin: str = ""

    @property
    def width(self):
        return int(self.format.partition("x")[0])

    @property
    def height(self):
        return int(self.format.partition("x")[2])


@dataclass(frozen=True)
class AdLayout:
    top_slots: tuple[AdSlot, ...] = ()
    feed_after: int | None = None
    feed_slots: tuple[AdSlot, ...] = ()
    watch_banner: AdSlot | None = None
    watch_sidebar: AdSlot | None = None
    bottom_slots: tuple[AdSlot, ...] = ()

    @property
    def origins(self):
        slots = (*self.top_slots, *self.feed_slots, self.watch_banner, self.watch_sidebar, *self.bottom_slots)
        return tuple(sorted({slot.origin for slot in slots if slot and slot.origin}))


RECTANGLE = ("300x250",)
HOME_TOP = (
    Placement("HOME_TOP_BANNER", "desktop", ("728x90",)),
    Placement("HOME_TOP_BANNER", "mobile", RECTANGLE),
)
HOME_FEED = (
    Placement("HOME_FEED_AD", "desktop", RECTANGLE),
    Placement("HOME_FEED_AD", "mobile", RECTANGLE),
)
# These configuration keys keep the existing ExoClick zones when moving them.
WATCH_BANNER = Placement("PLAY_TOP_BANNER", "desktop", ("728x90", "970x90"))
WATCH_SIDEBAR = Placement("PLAY_SIDEBAR_AD_1", "desktop", ("300x500", "300x250", "300x600"))
PLAY_FEED = (Placement("PLAY_SIDEBAR_AD_1", "mobile", RECTANGLE),)
PLAY_BOTTOM = (
    Placement("PLAY_BOTTOM_AD_1", "desktop", RECTANGLE),
    Placement("PLAY_BOTTOM_AD_1", "mobile", RECTANGLE),
)

HTTPS_URL = URLValidator(schemes=["https"])
DNS_HOST = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z][a-z0-9-]{0,61}[a-z0-9]"
)


def embed_origin(url):
    if not isinstance(url, str) or "\\" in url or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url
    ):
        return None

    try:
        HTTPS_URL(url)
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port
    except (ValidationError, ValueError):
        return None

    if (
        parsed.username is not None
        or len(host) > 253
        or not DNS_HOST.fullmatch(host)
        or host.endswith((".localhost", ".local", ".internal"))
        or port == 0
    ):
        return None

    return f"https://{host}:{port}" if port and port != 443 else f"https://{host}"


def _build_layout(
    configuration,
    video_count,
    feed,
    *,
    feed_after,
    top=(),
    watch_banner=None,
    watch_sidebar=None,
    bottom=(),
    allow_live_preview=False,
):
    preview = settings.DEVELOPMENT and settings.DEBUG and settings.PLAY_AD_PREVIEW

    def get_slot(placement):
        variants = configuration.get(placement.position, {})
        variant = variants.get(placement.device) if isinstance(variants, dict) else None
        if preview and variant is None:
            return AdSlot(placement.position, placement.device, placement.formats[0])
        if not isinstance(variant, dict) or variant.get("enabled") is not True:
            return None

        ad_format = variant.get("format")
        if ad_format not in placement.formats:
            return None

        url = "" if preview and not allow_live_preview else variant.get("url")
        origin = embed_origin(url)
        if origin:
            return AdSlot(placement.position, placement.device, ad_format, url, origin)
        if preview:
            return AdSlot(placement.position, placement.device, ad_format)
        return None

    feed_slots = ()
    if video_count >= feed_after:
        feed_slots = tuple(slot for placement in feed if (slot := get_slot(placement)))
    return AdLayout(
        top_slots=tuple(slot for placement in top if (slot := get_slot(placement))),
        feed_after=feed_after if feed_slots else None,
        feed_slots=feed_slots,
        watch_banner=get_slot(watch_banner) if watch_banner else None,
        watch_sidebar=get_slot(watch_sidebar) if watch_sidebar else None,
        bottom_slots=tuple(slot for placement in bottom if (slot := get_slot(placement))),
    )


def get_home_ad_layout(video_count):
    if not video_count:
        return AdLayout()
    return _build_layout(settings.HOME_ADS, video_count, HOME_FEED, feed_after=6, top=HOME_TOP, allow_live_preview=True)


def get_play_ad_layout(recommendation_count):
    return _build_layout(
        settings.PLAY_ADS,
        recommendation_count,
        PLAY_FEED,
        feed_after=3,
        watch_banner=WATCH_BANNER,
        watch_sidebar=WATCH_SIDEBAR,
        bottom=PLAY_BOTTOM,
    )
