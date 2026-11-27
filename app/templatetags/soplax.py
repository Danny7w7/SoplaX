from django import template


register = template.Library()


@register.filter
def vistas(value):
    """Formatea un contador de visitas de forma compacta: «12,4 k vistas»."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return ""
    if count < 1000:
        return "1 vista" if count == 1 else f"{count} vistas"
    number, suffix = round(count / 1000, 1), "k"
    if number >= 1000:
        number, suffix = round(count / 1_000_000, 1), "M"
    text = f"{number:.1f}".removesuffix(".0").replace(".", ",")
    return f"{text} {suffix} vistas"
