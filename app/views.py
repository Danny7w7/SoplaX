import logging
from pathlib import PurePosixPath
from urllib.parse import urlencode
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import PasswordResetConfirmView
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import InvalidPage, Paginator
from django.db import DatabaseError, IntegrityError, router, transaction
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Replace
from django.http import FileResponse, Http404, HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_safe
from django_ratelimit.core import is_ratelimited
from redis.exceptions import RedisError

from .account_mail import queue_account_email, send_password_reset_email, send_registration_email, token_digest
from .forms import AccountEmailForm, AccountSetPasswordForm, RegistrationForm
from .middleware import auth_service_unavailable
from .models import RegistroPendiente, Usuario, Videos
from .play_ads import AdLayout, get_home_ad_layout, get_play_ad_layout
from .video_uploads import VideoManagementForm, VideoUploadForm, store_video_uploads, thumbnail_webp_content


logger = logging.getLogger(__name__)
REGISTRATION_SESSION_KEY = "_registration_token_hash"
TITLE_SEARCH_REPLACEMENTS = {
    **dict(zip("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunaeiouun", strict=True)),
    "\N{COMBINING ACUTE ACCENT}": "",
    "\N{COMBINING TILDE}": "",
    "\N{COMBINING DIAERESIS}": "",
}
TITLE_SEARCH_TRANSLATION = str.maketrans(TITLE_SEARCH_REPLACEMENTS)
CATALOG_PAGE_SIZE = 24


def _catalog_url(page_number=1, query=""):
    params = {}
    if query:
        params["search"] = query
    if page_number != 1:
        params["page"] = page_number
    path = reverse("home")
    return f"{path}?{urlencode(params)}" if params else path


@require_http_methods(["GET", "HEAD", "POST"])
def index(request):
    if request.method == "POST":
        query = request.POST.get("search", "").strip()[:100]
        return redirect(_catalog_url(query=query))
    query = request.GET.get("search", "").strip()[:100]
    results = Videos.objects.order_by("pk")
    if query:
        searchable_title = F("nombre")
        for char, replacement in TITLE_SEARCH_REPLACEMENTS.items():
            searchable_title = Replace(searchable_title, Value(char), Value(replacement))
        results = results.alias(searchable_title=searchable_title)
        for term in query.split():
            normalized_term = term.translate(TITLE_SEARCH_TRANSLATION) or term
            results = results.filter(searchable_title__icontains=normalized_term)

    try:
        page = Paginator(results, CATALOG_PAGE_SIZE).page(request.GET.get("page", 1))
    except InvalidPage as exc:
        raise Http404("Esta página del catálogo no existe.") from exc

    videos = page.object_list
    ads = AdLayout() if query else get_home_ad_layout(len(videos))
    request.ad_frame_origins = ads.origins
    return render(
        request,
        "index.html",
        {
            "videos": videos,
            "page": page,
            "query": query,
            "canonical_url": "" if query else f"{settings.PUBLIC_BASE_URL}{_catalog_url(page.number)}",
            "previous_page_url": _catalog_url(page.previous_page_number(), query) if page.has_previous() else "",
            "next_page_url": _catalog_url(page.next_page_number(), query) if page.has_next() else "",
            "ads": ads,
        },
    )


def video_permission(action):
    def check_permission(user):
        if not user.is_active or not user.is_staff:
            raise PermissionDenied
        if user.is_superuser:
            return True
        if action == "view":
            allowed = user.has_perm("app.view_videos") or user.has_perm("app.change_videos")
        else:
            allowed = user.has_perm(f"app.{action}_videos")
        if not allowed:
            raise PermissionDenied
        return True

    return user_passes_test(check_permission)


def can_view_video_manager(user):
    return user.is_active and user.is_staff and (
        user.is_superuser or user.has_perm("app.view_videos") or user.has_perm("app.change_videos")
    )


def video_assets(video):
    assets = []
    for field_name in ("video", "miniatura"):
        asset = getattr(video, field_name)
        if asset and asset.name:
            assets.append((asset.storage, asset.name))
    return assets


def delete_unreferenced_video_assets(assets, *, using=None):
    failed = []
    deleted = set()
    using = using or router.db_for_write(Videos)
    for storage, name in assets:
        identity = (id(storage), name)
        if not name or identity in deleted:
            continue
        deleted.add(identity)
        try:
            still_referenced = Videos.objects.using(using).filter(Q(video=name) | Q(miniatura=name)).exists()
        except DatabaseError:
            logger.exception("No se pudo comprobar si el archivo sigue vinculado: %s", name)
            failed.append(name)
            continue
        if still_referenced:
            continue
        try:
            storage.delete(name)
        except Exception:
            logger.exception("No se pudo eliminar el archivo asociado al video: %s", name)
            failed.append(name)
    return failed


@require_GET
@login_required
@video_permission("view")
def video_manager(request):
    query = request.GET.get("q", "").strip()[:100]
    videos = Videos.objects.select_related("idioma").prefetch_related("categorias").order_by("-pk")
    if query:
        videos = videos.filter(
            Q(nombre__icontains=query)
            | Q(descripcion__icontains=query)
            | Q(categorias__nombre__icontains=query)
            | Q(actores__nombre__icontains=query)
            | Q(idioma__nombre__icontains=query)
            | Q(posturas__nombre__icontains=query)
        ).distinct()

    page = Paginator(videos, 20).get_page(request.GET.get("page"))
    totals = Videos.objects.aggregate(total=Count("pk"), visits=Sum("visitas"))
    return render(
        request,
        "video_manager_list.html",
        {
            "videos": page.object_list,
            "page": page,
            "query": query,
            "total_videos": totals["total"],
            "total_visits": totals["visits"] or 0,
            "can_add": request.user.is_superuser or request.user.has_perm("app.add_videos"),
            "can_change": request.user.is_superuser or request.user.has_perm("app.change_videos"),
            "can_delete": request.user.is_superuser or request.user.has_perm("app.delete_videos"),
        },
    )


@require_http_methods(["GET", "HEAD", "POST"])
@login_required
@video_permission("add")
def video_manager_add(request):
    form = VideoUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        video = form.save(commit=False)
        video.visitas = 0
        using = router.db_for_write(Videos)
        try:
            with store_video_uploads(video):
                with transaction.atomic(using=using):
                    video.save(using=using)
                    form.save_m2m()
        except (DatabaseError, OSError, BotoCoreError, ClientError):
            logger.exception("No se pudo crear un video desde el panel propio.")
            form.add_error(None, "No se pudo guardar el video. Vuelve a seleccionar los archivos.")
        else:
            messages.success(request, f"Se agregó «{video.nombre}» a la biblioteca.")
            return redirect("video_manager" if can_view_video_manager(request.user) else "video_manager_add")

    return render(
        request,
        "video_manager_form.html",
        {
            "form": form,
            "managed_video": None,
            "is_editing": False,
            "can_view_videos": can_view_video_manager(request.user),
        },
    )


@require_http_methods(["GET", "HEAD", "POST"])
@login_required
@video_permission("change")
def video_manager_edit(request, video_id):
    using = router.db_for_write(Videos)
    video = get_object_or_404(Videos.objects.using(using), pk=video_id)
    current_assets = {
        field_name: (getattr(video, field_name).storage, getattr(video, field_name).name)
        for field_name in ("video", "miniatura")
        if getattr(video, field_name) and getattr(video, field_name).name
    }
    original_premium = video.es_premium
    form = VideoManagementForm(request.POST or None, request.FILES or None, instance=video)
    if request.method == "POST" and form.is_valid():
        uploaded_fields = list(
            field_name
            for field_name in ("video", "miniatura")
            if form.files.get(form.add_prefix(field_name))
        )
        thumbnail_related = "miniatura" in uploaded_fields or (
            form.cleaned_data["es_premium"] != original_premium and "miniatura" in current_assets
        )
        old_assets = [current_assets[field_name] for field_name in uploaded_fields if field_name in current_assets]
        try:
            video = form.save(commit=False)
            if video.es_premium != original_premium and "miniatura" not in uploaded_fields and "miniatura" in current_assets:
                storage, old_name = current_assets["miniatura"]
                with storage.open(old_name, "rb") as thumbnail:
                    webp = thumbnail_webp_content(thumbnail.read())
                replacement = ContentFile(webp, name=f"{uuid4().hex}.webp")
                replacement.content_type = "image/webp"
                video.miniatura = replacement
                uploaded_fields.append("miniatura")
                old_assets.append(current_assets["miniatura"])
            with store_video_uploads(video, fields=uploaded_fields):
                with transaction.atomic(using=using):
                    video.save(using=using, update_fields=form.video_update_fields() | set(uploaded_fields))
                    form.save_m2m()
        except (DatabaseError, OSError, BotoCoreError, ClientError, ValueError):
            logger.exception("No se pudo actualizar el video %s desde el panel propio.", video_id)
            form.add_error(
                "miniatura" if thumbnail_related else None,
                "No se pudo guardar el video. Vuelve a seleccionar los archivos.",
            )
        else:
            failed = delete_unreferenced_video_assets(old_assets, using=using)
            if failed:
                messages.warning(
                    request,
                    "El video se guardó, pero no se pudieron retirar todos los archivos reemplazados de S3.",
                )
            else:
                messages.success(request, f"Se guardaron los cambios de «{video.nombre}».")
            return redirect("video_manager")

    return render(
        request,
        "video_manager_form.html",
        {
            "form": form,
            "managed_video": get_object_or_404(Videos.objects.using(using), pk=video_id),
            "is_editing": True,
            "can_view_videos": can_view_video_manager(request.user),
        },
    )


@never_cache
@require_safe
@login_required
@video_permission("change")
def video_manager_thumbnail_download(request, video_id):
    using = router.db_for_write(Videos)
    video = get_object_or_404(Videos.objects.using(using), pk=video_id)
    if not video.miniatura:
        raise Http404("Este video no tiene miniatura.")
    try:
        thumbnail = video.miniatura.open("rb")
    except (BotoCoreError, ClientError, OSError):
        logger.exception("No se pudo abrir la miniatura del video %s.", video_id)
        raise Http404("La miniatura no está disponible.")
    return FileResponse(
        thumbnail,
        as_attachment=True,
        filename=PurePosixPath(video.miniatura.name).name,
    )


@require_http_methods(["GET", "HEAD", "POST"])
@login_required
@video_permission("delete")
def video_manager_delete(request, video_id):
    using = router.db_for_write(Videos)
    video = get_object_or_404(Videos.objects.using(using), pk=video_id)
    if request.method == "POST":
        title = video.nombre
        assets = video_assets(video)
        try:
            with transaction.atomic(using=using):
                video.delete(using=using)
        except DatabaseError:
            logger.exception("No se pudo eliminar el video %s desde el panel propio.", video_id)
            messages.error(request, "No se pudo eliminar el video. Inténtalo de nuevo.")
        else:
            failed = delete_unreferenced_video_assets(assets, using=using)
            if failed:
                messages.warning(
                    request,
                    f"Se eliminó «{title}», pero no se pudieron retirar todos sus archivos de S3.",
                )
            else:
                messages.success(request, f"Se eliminó «{title}» y sus archivos asociados.")
        return redirect("video_manager" if can_view_video_manager(request.user) else "admin:index")

    return render(
        request,
        "video_manager_delete.html",
        {"managed_video": video, "can_view_videos": can_view_video_manager(request.user)},
    )


def account_email_request(request, *, task, title, instruction):
    form = AccountEmailForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        email = form.cleaned_data["email"]
        try:
            limited = is_ratelimited(
                request,
                group=task.__name__,
                key=lambda group, request: email,
                rate="3/h",
                method="POST",
                increment=True,
            )
            if not limited:
                queue_account_email(task, email)
        except RedisError:
            logger.warning("El servicio de cuentas no pudo conectar con Redis.")
            return auth_service_unavailable()
        return redirect("account_email_sent")
    return render(request, "account_email.html", {"form": form, "title": title, "instruction": instruction})


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def register(request):
    return account_email_request(
        request,
        task=send_registration_email,
        title="Crear cuenta",
        instruction="Ingresa tu correo. Recibirás un enlace para completar el registro.",
    )


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def recover_password(request):
    return account_email_request(
        request,
        task=send_password_reset_email,
        title="Recuperar contraseña",
        instruction="Ingresa el correo asociado a tu cuenta.",
    )


@never_cache
@require_safe
def account_email_sent(request):
    return render(request, "account_email_sent.html")


def valid_registrations():
    return RegistroPendiente.objects.filter(expires_at__gt=timezone.now())


@never_cache
@require_GET
def register_token(request, token):
    digest = token_digest(token)
    if valid_registrations().filter(pk=digest).exists():
        request.session[REGISTRATION_SESSION_KEY] = digest
    else:
        request.session.pop(REGISTRATION_SESSION_KEY, None)
    return redirect("register_confirm")


@sensitive_post_parameters()
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def register_confirm(request):
    digest = request.session.get(REGISTRATION_SESSION_KEY)
    registration = valid_registrations().filter(pk=digest).first()
    if registration is None:
        return render(request, "register_confirm.html")

    form = RegistrationForm(
        request.POST if request.method == "POST" else None, email=registration.email
    )
    if form.is_valid():
        try:
            with transaction.atomic():
                registration = valid_registrations().select_for_update().filter(pk=digest).first()
                if registration is None or Usuario.objects.filter(email=registration.email).exists():
                    return render(request, "register_confirm.html")
                user = form.save()
                registration.delete()
        except IntegrityError:
            # The unique email constraint resolves simultaneous confirmations of different links.
            if Usuario.objects.filter(email=form.instance.email).exists():
                return render(request, "register_confirm.html")
            raise
        request.session.pop(REGISTRATION_SESSION_KEY, None)
        login(request, user)
        return redirect("home")
    return render(request, "register_confirm.html", {"form": form})


class AccountPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = AccountSetPasswordForm
    template_name = "password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")
    http_method_names = ["get", "head", "post", "options"]

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            with transaction.atomic():
                return super().dispatch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        if user is not None and self.request.method == "POST":
            # Check the reset token against the current password under the same lock as the save.
            user = Usuario.objects.select_for_update().filter(pk=user.pk).first()
        if user is not None and user.is_active and user.has_usable_password():
            return user
        return None


def video_recommendations(video):
    limit = 12
    candidates = Videos.objects.exclude(pk=video.pk).exclude(video="").order_by("-visitas", "pk")
    recommendations = list(
        candidates.filter(categorias__in=video.categorias.all())
        .alias(shared_categories=Count("categorias"))
        .order_by("-shared_categories", "-visitas", "pk")[:limit]
    )
    remaining = limit - len(recommendations)
    if remaining:
        recommended_ids = [item.pk for item in recommendations]
        recommendations.extend(candidates.exclude(pk__in=recommended_ids)[:remaining])
    return recommendations


@require_safe
def play_(request, id, slug=None):
    video = get_object_or_404(Videos.objects.exclude(video=""), pk=id)
    canonical_path = video.get_absolute_url()
    if slug is None or request.path != canonical_path:
        query = request.GET.urlencode()
        target = f"{canonical_path}?{query}" if query else canonical_path
        return HttpResponsePermanentRedirect(target)

    if request.method == "GET":
        Videos.objects.filter(pk=video.pk).update(visitas=F("visitas") + 1)
    recommended_videos = video_recommendations(video)
    ads = get_play_ad_layout(len(recommended_videos))
    request.ad_frame_origins = ads.origins
    return render(
        request,
        "play.html",
        {
            "video": video,
            "canonical_url": f"{settings.PUBLIC_BASE_URL}{canonical_path}",
            "recommended_videos": recommended_videos,
            "ads": ads,
        },
    )


@require_safe
def redirect_(request):
    return render(request, "redirect.html", {"public_base_url": settings.PUBLIC_BASE_URL})
