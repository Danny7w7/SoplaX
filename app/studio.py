"""SoplaX Studio: panel de administración propio (resumen, clasificación, usuarios y roles)."""
import logging
import operator
from dataclasses import dataclass
from datetime import timedelta
from functools import reduce, wraps
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.core.validators import MaxLengthValidator
from django.db import DatabaseError, transaction
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_safe

from .forms import AccountSetPasswordForm
from .models import Actor, Categoria, Idioma, Postura, Usuario, Videos, normalize_account_email


logger = logging.getLogger(__name__)
PAGE_SIZE = 25
MAX_BULK_NAMES = 200


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

def is_studio_user(user):
    return user.is_authenticated and user.is_active and user.is_staff


def has_model_perm(user, action, model):
    """Permiso de modelo de Django; «ver» también se concede a quien puede editar."""
    if not is_studio_user(user):
        return False
    if user.is_superuser:
        return True
    label = f"{model._meta.app_label}.%s_{model._meta.model_name}"
    if action == "view":
        return user.has_perm(label % "view") or user.has_perm(label % "change")
    return user.has_perm(label % action)


def studio_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_studio_user(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def superuser_required(view):
    @wraps(view)
    @studio_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def require_model_perm(user, action, model):
    if not has_model_perm(user, action, model):
        raise PermissionDenied


# ---------------------------------------------------------------------------
# Clasificación: categorías, actores, idiomas y posturas
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CatalogKind:
    slug: str
    model: type
    plural: str
    singular: str
    new_label: str
    description: str
    delete_effect: str


CATALOG_KINDS = {
    kind.slug: kind
    for kind in (
        CatalogKind(
            "categorias", Categoria, "Categorías", "categoría", "Nueva categoría",
            "Agrupan los videos por temática en el catálogo.",
            "Se quitará de {count} video{plural}; los videos no se eliminan.",
        ),
        CatalogKind(
            "actores", Actor, "Actores", "actor o actriz", "Nuevo actor o actriz",
            "Actrices y actores que aparecen en los videos.",
            "Se quitará de {count} video{plural}; los videos no se eliminan.",
        ),
        CatalogKind(
            "idiomas", Idioma, "Idiomas", "idioma", "Nuevo idioma",
            "Idioma principal de cada video.",
            "{count} video{plural} quedará{plural_verb} sin idioma; los videos no se eliminan.",
        ),
        CatalogKind(
            "posturas", Postura, "Posturas", "postura", "Nueva postura",
            "Posturas presentes en los videos.",
            "Se quitará de {count} video{plural}; los videos no se eliminan.",
        ),
    )
}


def get_catalog_kind(slug):
    try:
        return CATALOG_KINDS[slug]
    except KeyError:
        raise Http404("Esta sección del catálogo no existe.") from None


class CatalogNamesForm(forms.Form):
    nombres = forms.CharField(
        label="Nombres",
        max_length=MAX_BULK_NAMES * 101,
        widget=forms.Textarea(attrs={"class": "input", "rows": 8, "autocomplete": "off"}),
        help_text="Escribe uno por línea. Los que ya existan se omitirán.",
    )

    def clean_nombres(self):
        names, seen = [], set()
        for line in self.cleaned_data["nombres"].splitlines():
            name = " ".join(line.split())
            if not name or name.casefold() in seen:
                continue
            if len(name) > 100:
                raise forms.ValidationError(f"«{name[:40]}…» supera los 100 caracteres.")
            seen.add(name.casefold())
            names.append(name)
        if not names:
            raise forms.ValidationError("Escribe al menos un nombre.")
        if len(names) > MAX_BULK_NAMES:
            raise forms.ValidationError(f"Puedes agregar hasta {MAX_BULK_NAMES} nombres a la vez.")
        return names


class CatalogItemForm(forms.Form):
    nombre = forms.CharField(label="Nombre", max_length=100, widget=forms.TextInput(attrs={"autocomplete": "off"}))

    def __init__(self, *args, model, instance, **kwargs):
        super().__init__(*args, initial={"nombre": instance.nombre}, **kwargs)
        self.model = model
        self.instance = instance

    def clean_nombre(self):
        name = " ".join(self.cleaned_data["nombre"].split())
        if not name:
            raise forms.ValidationError("Escribe un nombre.")
        if self.model.objects.filter(nombre__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un elemento con este nombre.")
        return name


def create_catalog_items(model, names):
    """Crea los nombres que no existan (sin distinguir mayúsculas) y devuelve (creados, omitidos)."""
    matches = reduce(operator.or_, (Q(nombre__iexact=name) for name in names))
    existing = {name.casefold() for name in model.objects.filter(matches).values_list("nombre", flat=True)}
    created = [name for name in names if name.casefold() not in existing]
    skipped = [name for name in names if name.casefold() in existing]
    model.objects.bulk_create([model(nombre=name) for name in created])
    return created, skipped


def count_label(count, singular, plural):
    return f"{count} {singular if count == 1 else plural}"


@require_safe
@studio_required
def catalog_list(request, kind):
    kind = get_catalog_kind(kind)
    require_model_perm(request.user, "view", kind.model)
    query = " ".join(request.GET.get("q", "").split())[:100]
    order = request.GET.get("orden", "nombre")
    items = kind.model.objects.annotate(total_videos=Count("videos", distinct=True))
    if query:
        items = items.filter(nombre__icontains=query)
    items = items.order_by("-total_videos", "nombre") if order == "videos" else items.order_by("nombre")
    page = Paginator(items, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "studio/catalog_list.html",
        {
            "kind": kind,
            "page": page,
            "items": page.object_list,
            "query": query,
            "order": "videos" if order == "videos" else "nombre",
            "total": kind.model.objects.count(),
            "quick_form": CatalogNamesForm(),
            "can_add": has_model_perm(request.user, "add", kind.model),
            "can_change": has_model_perm(request.user, "change", kind.model),
            "can_delete": has_model_perm(request.user, "delete", kind.model),
        },
    )


@require_http_methods(["GET", "HEAD", "POST"])
@studio_required
def catalog_add(request, kind):
    kind = get_catalog_kind(kind)
    require_model_perm(request.user, "add", kind.model)
    form = CatalogNamesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                created, skipped = create_catalog_items(kind.model, form.cleaned_data["nombres"])
        except DatabaseError:
            logger.exception("No se pudieron crear elementos de %s.", kind.slug)
            form.add_error(None, "No se pudo guardar. Vuelve a intentarlo.")
        else:
            if created:
                messages.success(request, f"Se agregaron {len(created)} a {kind.plural.lower()}: {', '.join(created)}.")
            if skipped:
                messages.warning(request, f"Ya existían y se omitieron: {', '.join(skipped)}.")
            return redirect("studio_catalog", kind=kind.slug)
    return render(request, "studio/catalog_form.html", {"kind": kind, "form": form, "item": None})


@require_http_methods(["GET", "HEAD", "POST"])
@studio_required
def catalog_edit(request, kind, pk):
    kind = get_catalog_kind(kind)
    require_model_perm(request.user, "change", kind.model)
    item = get_object_or_404(kind.model, pk=pk)
    form = CatalogItemForm(request.POST or None, model=kind.model, instance=item)
    if request.method == "POST" and form.is_valid():
        previous = item.nombre
        item.nombre = form.cleaned_data["nombre"]
        try:
            item.save(update_fields=["nombre"])
        except DatabaseError:
            logger.exception("No se pudo renombrar %s %s.", kind.slug, pk)
            form.add_error(None, "No se pudo guardar. Vuelve a intentarlo.")
        else:
            messages.success(request, f"«{previous}» ahora se llama «{item.nombre}».")
            return redirect("studio_catalog", kind=kind.slug)
    return render(
        request,
        "studio/catalog_form.html",
        {"kind": kind, "form": form, "item": item, "total_videos": item.videos.count()},
    )


@require_http_methods(["GET", "HEAD", "POST"])
@studio_required
def catalog_delete(request, kind, pk):
    kind = get_catalog_kind(kind)
    require_model_perm(request.user, "delete", kind.model)
    item = get_object_or_404(kind.model, pk=pk)
    total = item.videos.count()
    if request.method == "POST":
        name = item.nombre
        try:
            with transaction.atomic():
                item.delete()
        except DatabaseError:
            logger.exception("No se pudo eliminar %s %s.", kind.slug, pk)
            messages.error(request, "No se pudo eliminar. Vuelve a intentarlo.")
        else:
            messages.success(request, f"Se eliminó «{name}».")
        return redirect("studio_catalog", kind=kind.slug)
    effect = kind.delete_effect.format(
        count=total, plural="" if total == 1 else "s", plural_verb="" if total == 1 else "n"
    )
    return render(request, "studio/catalog_delete.html", {"kind": kind, "item": item, "effect": effect})


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

@require_safe
@studio_required
def dashboard(request):
    user = request.user
    stats, actions = [], []
    context = {"stats": stats, "actions": actions}

    if has_model_perm(user, "view", Videos):
        totals = Videos.objects.aggregate(
            total=Count("pk"), visits=Sum("visitas"), premium=Count("pk", filter=Q(es_premium=True))
        )
        stats.append({
            "label": "Videos publicados", "value": totals["total"], "url": reverse("video_manager"),
            "hint": count_label(totals["premium"], "premium", "premium"),
        })
        stats.append({"label": "Reproducciones", "value": totals["visits"] or 0, "url": reverse("video_manager")})
        videos = Videos.objects.only("pk", "nombre", "miniatura", "visitas", "es_premium")
        context["top_videos"] = videos.order_by("-visitas", "-pk")[:5]
        context["recent_videos"] = videos.order_by("-pk")[:5]
        unclassified = Videos.objects.annotate(total_categorias=Count("categorias")).filter(total_categorias=0)
        context["unclassified_total"] = unclassified.count()
        context["unclassified_videos"] = unclassified.only("pk", "nombre", "miniatura").order_by("-pk")[:5]
        context["missing_duration"] = Videos.objects.filter(duracion_segundos__isnull=True).count()
        context["can_change_videos"] = has_model_perm(user, "change", Videos)
        context["can_view_videos"] = True
    if has_model_perm(user, "add", Videos):
        actions.append({"label": "Subir video", "url": reverse("video_manager_add"), "primary": True})

    for kind in CATALOG_KINDS.values():
        if has_model_perm(user, "view", kind.model):
            stats.append({
                "label": kind.plural, "value": kind.model.objects.count(),
                "url": reverse("studio_catalog", kwargs={"kind": kind.slug}),
            })
        if has_model_perm(user, "add", kind.model):
            actions.append({"label": kind.new_label, "url": reverse("studio_catalog_add", kwargs={"kind": kind.slug})})

    if user.is_superuser:
        week_ago = timezone.now() - timedelta(days=7)
        accounts = Usuario.objects.aggregate(
            total=Count("pk"),
            staff=Count("pk", filter=Q(is_staff=True, is_active=True)),
            new=Count("pk", filter=Q(date_joined__gte=week_ago)),
        )
        stats.append({
            "label": "Usuarios", "value": accounts["total"], "url": reverse("studio_users"),
            "hint": f"{accounts['new']} nuevos esta semana · {accounts['staff']} en el equipo",
        })
        actions.append({"label": "Nuevo usuario", "url": reverse("studio_user_add")})

    return render(request, "studio/dashboard.html", context)


# ---------------------------------------------------------------------------
# Usuarios (solo superusuarios)
# ---------------------------------------------------------------------------

USER_FILTERS = {
    "todos": ("Todos", Q()),
    "equipo": ("Equipo", Q(is_staff=True)),
    "superusuarios": ("Superusuarios", Q(is_superuser=True)),
    "inactivos": ("Inactivos", Q(is_active=False)),
}


class GroupChoiceField(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, obj):
        return obj.name


class StudioUserFieldsMixin:
    def setup_fields(self):
        self.fields["email"].required = True
        self.fields["email"].label = "Correo electrónico"
        self.fields["first_name"].label = "Nombre"
        self.fields["last_name"].label = "Apellido"
        self.fields["email"].widget.attrs["autocomplete"] = "off"
        if "is_staff" in self.fields:
            self.fields["is_staff"].label = "Acceso al panel"
            self.fields["is_staff"].help_text = "Permite entrar a SoplaX Studio con los permisos de sus roles."

    def clean_email(self):
        email = normalize_account_email(self.cleaned_data.get("email"))
        duplicates = Usuario.objects.filter(email__iexact=email)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return email


class StudioUserForm(StudioUserFieldsMixin, forms.ModelForm):
    groups = GroupChoiceField(queryset=Group.objects.order_by("name"), required=False, label="Roles")

    class Meta:
        model = Usuario
        fields = ("first_name", "last_name", "email", "is_active", "is_staff", "is_superuser", "groups")

    def __init__(self, *args, acting_user, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_fields()
        self.fields["is_active"].label = "Cuenta activa"
        self.fields["is_active"].help_text = "Las cuentas inactivas no pueden iniciar sesión."
        self.fields["is_superuser"].label = "Superusuario"
        self.fields["is_superuser"].help_text = "Tiene todos los permisos, incluida la gestión de usuarios y roles."
        if self.instance.pk == acting_user.pk:
            for name in ("is_active", "is_staff", "is_superuser"):
                self.fields[name].disabled = True
            self.fields["is_superuser"].help_text = "No puedes quitarte tu propio acceso."


class StudioUserCreateForm(StudioUserFieldsMixin, UserCreationForm):
    groups = GroupChoiceField(queryset=Group.objects.order_by("name"), required=False, label="Roles")

    class Meta:
        model = Usuario
        fields = ("first_name", "last_name", "email", "is_staff", "groups")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_fields()
        self.instance.username = uuid4().hex
        for name in ("password1", "password2"):
            self.fields[name].validators.append(MaxLengthValidator(4096))
            self.fields[name].widget.attrs["autocomplete"] = "new-password"
        spanish_password_labels(self.fields, "password1", "password2")


PASSWORD_HELP = "Al menos 12 caracteres. No puede ser solo números, muy común ni parecida a los datos de la cuenta."


def spanish_password_labels(fields, first, second):
    fields[first].label = "Contraseña"
    fields[first].help_text = PASSWORD_HELP
    fields[second].label = "Confirma la contraseña"
    fields[second].help_text = "Escribe la misma contraseña para verificarla."


@require_safe
@superuser_required
def user_list(request):
    query = " ".join(request.GET.get("q", "").split())[:100]
    active_filter = request.GET.get("filtro", "todos")
    if active_filter not in USER_FILTERS:
        active_filter = "todos"
    users = Usuario.objects.filter(USER_FILTERS[active_filter][1]).prefetch_related("groups")
    for term in query.split():
        users = users.filter(
            Q(first_name__icontains=term) | Q(last_name__icontains=term)
            | Q(email__icontains=term) | Q(username__icontains=term)
        )
    page = Paginator(users.order_by("-is_superuser", "-is_staff", "-date_joined"), PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "studio/user_list.html",
        {
            "page": page,
            "users": page.object_list,
            "query": query,
            "filters": [(key, label) for key, (label, _) in USER_FILTERS.items()],
            "active_filter": active_filter,
        },
    )


@require_http_methods(["GET", "HEAD", "POST"])
@superuser_required
def user_add(request):
    form = StudioUserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                account = form.save()
        except DatabaseError:
            logger.exception("No se pudo crear un usuario desde el panel.")
            form.add_error(None, "No se pudo crear la cuenta. Vuelve a intentarlo.")
        else:
            messages.success(request, f"Se creó la cuenta de {account.email}.")
            return redirect("studio_users")
    return render(request, "studio/user_form.html", {"form": form, "account": None})


@require_http_methods(["GET", "HEAD", "POST"])
@superuser_required
def user_edit(request, pk):
    account = get_object_or_404(Usuario, pk=pk)
    form = StudioUserForm(request.POST or None, instance=account, acting_user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                account = form.save()
        except DatabaseError:
            logger.exception("No se pudo actualizar el usuario %s.", pk)
            form.add_error(None, "No se pudieron guardar los cambios. Vuelve a intentarlo.")
        else:
            messages.success(request, f"Se guardaron los cambios de {account.email or account.username}.")
            return redirect("studio_users")
    return render(request, "studio/user_form.html", {"form": form, "account": account})


@require_http_methods(["GET", "HEAD", "POST"])
@superuser_required
def user_password(request, pk):
    account = get_object_or_404(Usuario, pk=pk)
    form = AccountSetPasswordForm(account, request.POST or None)
    spanish_password_labels(form.fields, "new_password1", "new_password2")
    form.fields["new_password1"].label = "Nueva contraseña"
    if request.method == "POST" and form.is_valid():
        form.save()
        if account.pk == request.user.pk:
            update_session_auth_hash(request, account)
        messages.success(request, f"Se cambió la contraseña de {account.email or account.username}.")
        return redirect("studio_user_edit", pk=account.pk)
    return render(request, "studio/user_password.html", {"form": form, "account": account})


# ---------------------------------------------------------------------------
# Roles (grupos de Django) con permisos sobre el contenido
# ---------------------------------------------------------------------------

ROLE_MODELS = (
    (Videos, "Videos"),
    (Categoria, "Categorías"),
    (Actor, "Actores"),
    (Idioma, "Idiomas"),
    (Postura, "Posturas"),
)
ROLE_ACTIONS = (("view", "Ver"), ("add", "Crear"), ("change", "Editar"), ("delete", "Eliminar"))


def role_permissions():
    content_types = ContentType.objects.get_for_models(*(model for model, _ in ROLE_MODELS))
    permissions = Permission.objects.filter(content_type__in=content_types.values()).select_related("content_type")
    return {(perm.content_type.model, perm.codename.split("_", 1)[0]): perm for perm in permissions}


class RoleForm(forms.ModelForm):
    permisos = forms.ModelMultipleChoiceField(queryset=Permission.objects.none(), required=False)

    class Meta:
        model = Group
        fields = ("name",)
        labels = {"name": "Nombre del rol"}
        widgets = {"name": forms.TextInput(attrs={"autocomplete": "off"})}

    def __init__(self, *args, permissions, **kwargs):
        super().__init__(*args, **kwargs)
        self.managed = permissions
        self.fields["permisos"].queryset = Permission.objects.filter(pk__in=[p.pk for p in permissions.values()])
        if self.instance.pk:
            self.fields["permisos"].initial = list(
                self.instance.permissions.filter(pk__in=[p.pk for p in permissions.values()]).values_list("pk", flat=True)
            )

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        duplicates = Group.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("Ya existe un rol con este nombre.")
        return name

    def selected_ids(self):
        if self.is_bound:
            return {str(value) for value in self.data.getlist(self.add_prefix("permisos"))}
        return {str(pk) for pk in self.fields["permisos"].initial or []}

    def matrix(self):
        selected = self.selected_ids()
        rows = []
        for model, label in ROLE_MODELS:
            cells = []
            for action, action_label in ROLE_ACTIONS:
                perm = self.managed.get((model._meta.model_name, action))
                cells.append({
                    "action": action_label,
                    "perm": perm,
                    "checked": perm is not None and str(perm.pk) in selected,
                })
            rows.append({"label": label, "cells": cells})
        return rows

    def save(self, commit=True):
        role = super().save(commit=commit)
        managed_ids = {perm.pk for perm in self.managed.values()}
        kept = role.permissions.exclude(pk__in=managed_ids)
        role.permissions.set(list(kept) + list(self.cleaned_data["permisos"]))
        return role


@require_safe
@superuser_required
def role_list(request):
    roles = Group.objects.annotate(
        total_users=Count("user", distinct=True), total_permissions=Count("permissions", distinct=True)
    ).order_by("name")
    return render(request, "studio/role_list.html", {"roles": roles, "actions": ROLE_ACTIONS})


@require_http_methods(["GET", "HEAD", "POST"])
@superuser_required
def role_form(request, pk=None):
    role = get_object_or_404(Group, pk=pk) if pk else Group()
    form = RoleForm(request.POST or None, instance=role, permissions=role_permissions())
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                role = form.save()
        except DatabaseError:
            logger.exception("No se pudo guardar el rol %s.", pk)
            form.add_error(None, "No se pudo guardar el rol. Vuelve a intentarlo.")
        else:
            messages.success(request, f"Se guardó el rol «{role.name}».")
            return redirect("studio_roles")
    return render(
        request,
        "studio/role_form.html",
        {"form": form, "role": role if pk else None, "matrix": form.matrix(), "actions": ROLE_ACTIONS},
    )


@require_http_methods(["GET", "HEAD", "POST"])
@superuser_required
def role_delete(request, pk):
    role = get_object_or_404(Group, pk=pk)
    members = role.user_set.count()
    if request.method == "POST":
        name = role.name
        try:
            role.delete()
        except DatabaseError:
            logger.exception("No se pudo eliminar el rol %s.", pk)
            messages.error(request, "No se pudo eliminar el rol. Vuelve a intentarlo.")
        else:
            messages.success(request, f"Se eliminó el rol «{name}».")
        return redirect("studio_roles")
    if members:
        message = (
            f"{count_label(members, 'persona perderá', 'personas perderán')} los permisos de este rol. "
            "Sus cuentas no se eliminan."
        )
    else:
        message = "Nadie tiene este rol asignado."
    return render(request, "studio/role_delete.html", {"role": role, "message": message})
