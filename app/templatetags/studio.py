from django import template
from django.urls import reverse

from app.models import Videos
from app.studio import CATALOG_KINDS, has_model_perm


register = template.Library()


def active_section(request):
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    name = match.url_name or ""
    if name.startswith("video_manager"):
        return "videos"
    if name.startswith("studio_catalog"):
        return match.kwargs.get("kind", "")
    if name.startswith("studio_user"):
        return "usuarios"
    if name.startswith("studio_role"):
        return "roles"
    return "resumen" if name == "studio_dashboard" else ""


@register.inclusion_tag("studio/partials/nav.html", takes_context=True)
def studio_nav(context):
    request = context["request"]
    user = request.user
    groups = [{"label": "General", "items": [("resumen", "Resumen", reverse("studio_dashboard"), "dashboard")]}]

    content = []
    if has_model_perm(user, "view", Videos):
        content.append(("videos", "Videos", reverse("video_manager"), "video"))
    elif has_model_perm(user, "add", Videos):
        content.append(("videos", "Subir video", reverse("video_manager_add"), "video"))
    if content:
        groups.append({"label": "Contenido", "items": content})

    icons = {"categorias": "tag", "actores": "star", "idiomas": "globe", "posturas": "layers"}
    catalog = [
        (kind.slug, kind.plural, reverse("studio_catalog", kwargs={"kind": kind.slug}), icons[kind.slug])
        for kind in CATALOG_KINDS.values()
        if has_model_perm(user, "view", kind.model)
    ]
    if catalog:
        groups.append({"label": "Clasificación", "items": catalog})

    if user.is_superuser:
        groups.append({
            "label": "Acceso",
            "items": [
                ("usuarios", "Usuarios", reverse("studio_users"), "users"),
                ("roles", "Roles y permisos", reverse("studio_roles"), "shield"),
            ],
        })

    return {"groups": groups, "active": active_section(request), "user": user}


@register.inclusion_tag("studio/partials/icon.html")
def studio_icon(name):
    return {"name": name}


@register.filter
def miles(value):
    """Cifra con punto de miles: 12345 → «12.345»."""
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return value
