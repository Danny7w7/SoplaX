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
    after_card: int | None = None
    preview_default: bool = True


@dataclass(frozen=True)
class AdSlot:
    position: str
    device: str
    format: str
    after_card: int | None
    url: str = ""
    origin: str = ""

    @property
    def eager(self):
        return self.position == "PLAY_TOP_BANNER"

    @property
    def width(self):
        return self.format.split("x")[0] if self.format != "native" else ""


@dataclass(frozen=True)
class PlayAdLayout:
    top_desktop: AdSlot | None
    top_mobile: AdSlot | None
    sidebar: tuple[AdSlot, ...]
    bottom_desktop: tuple[AdSlot, ...]
    bottom_mobile: AdSlot | None
    feed: tuple[AdSlot, ...]

    @property
    def origins(self):
        slots = (self.top_desktop, self.top_mobile, self.bottom_mobile, *self.sidebar, *self.bottom_desktop, *self.feed)
        return sorted({slot.origin for slot in slots if slot and slot.origin})


RECTANGLE = ("300x250",)
TOP_DESKTOP = Placement("PLAY_TOP_BANNER", "desktop", ("970x90", "728x90"))
TOP_MOBILE = Placement("PLAY_TOP_BANNER", "mobile", ("320x50", "320x100"))
SIDEBAR = tuple(
    Placement(f"PLAY_SIDEBAR_AD_{index}", "desktop", ("300x250", "300x600"))
    for index in range(1, 4)
)
BOTTOM = tuple(Placement(f"PLAY_BOTTOM_AD_{index}", "desktop", RECTANGLE) for index in range(1, 4))
BOTTOM_MOBILE = Placement("PLAY_BOTTOM_AD_1", "mobile", RECTANGLE)
FEED = (
    Placement("PLAY_SIDEBAR_AD_1", "mobile", RECTANGLE, after_card=3),
    Placement("PLAY_RECOMMENDED_NATIVE", "desktop", ("native",), after_card=5),
    Placement("PLAY_RECOMMENDED_NATIVE", "mobile", ("native",), after_card=5),
    Placement("PLAY_SIDEBAR_AD_2", "mobile", RECTANGLE, after_card=8, preview_default=False),
    Placement("PLAY_SIDEBAR_AD_3", "mobile", RECTANGLE, after_card=11, preview_default=False),
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


def get_play_ad_layout():
    configuration = settings.PLAY_ADS
    preview = settings.DEVELOPMENT and settings.DEBUG and settings.PLAY_AD_PREVIEW

    def get_slot(placement):
        variants = configuration.get(placement.position, {})
        variant = variants.get(placement.device) if isinstance(variants, dict) else None
        if preview and variant is None and placement.preview_default:
            variant = {"enabled": True, "format": placement.formats[0]}
        if not isinstance(variant, dict) or variant.get("enabled") is not True:
            return None

        ad_format = variant.get("format")
        if ad_format not in placement.formats:
            return None

        url = ""
        origin = ""
        if not preview:
            url = variant.get("url")
            origin = embed_origin(url)
            if not origin:
                return None

        return AdSlot(placement.position, placement.device, ad_format, placement.after_card, url, origin)

    def get_slots(placements):
        return tuple(slot for placement in placements if (slot := get_slot(placement)))

    return PlayAdLayout(
        top_desktop=get_slot(TOP_DESKTOP),
        top_mobile=get_slot(TOP_MOBILE),
        sidebar=get_slots(SIDEBAR),
        bottom_desktop=get_slots(BOTTOM),
        bottom_mobile=get_slot(BOTTOM_MOBILE),
        feed=get_slots(FEED),
    )
