from xml.etree.ElementTree import Element, SubElement, tostring

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_safe

from .models import Videos


SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
VIDEOS_PER_SITEMAP = 10_000


def _public_url(path):
    return f"{settings.PUBLIC_BASE_URL}{path}"


def _video_paginator():
    videos = Videos.objects.exclude(video="").only("pk", "nombre").order_by("pk")
    return Paginator(videos, VIDEOS_PER_SITEMAP)


def _xml_response(root_tag, entry_tag, locations):
    root = Element(root_tag, xmlns=SITEMAP_NAMESPACE)
    for location in locations:
        entry = SubElement(root, entry_tag)
        SubElement(entry, "loc").text = location
    return HttpResponse(
        tostring(root, encoding="utf-8", xml_declaration=True),
        content_type="application/xml",
    )


@require_safe
def sitemap_index(request):
    locations = (
        _public_url(reverse("sitemap_videos", kwargs={"page": page}))
        for page in _video_paginator().page_range
    )
    return _xml_response("sitemapindex", "sitemap", locations)


@require_safe
def sitemap_videos(request, page):
    try:
        video_page = _video_paginator().page(page)
    except EmptyPage as exc:
        raise Http404 from exc

    locations = [_public_url(reverse("home"))] if page == 1 else []
    locations.extend(_public_url(video.get_absolute_url()) for video in video_page)
    return _xml_response("urlset", "url", locations)


@require_safe
def robots_txt(request):
    sitemap_url = _public_url(reverse("sitemap_index"))
    return HttpResponse(
        f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n",
        content_type="text/plain; charset=utf-8",
    )
