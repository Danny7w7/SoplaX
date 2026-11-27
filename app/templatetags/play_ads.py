from django import template

from app.play_ads import get_play_ad_layout


register = template.Library()


@register.simple_tag
def play_ad_layout():
    return get_play_ad_layout()
