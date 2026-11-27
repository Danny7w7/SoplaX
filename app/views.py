import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import PasswordResetConfirmView
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Value
from django.db.models.functions import Replace
from django.http import Http404
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


logger = logging.getLogger(__name__)
REGISTRATION_SESSION_KEY = "_registration_token_hash"
TITLE_SEARCH_REPLACEMENTS = {
    **dict(zip("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunaeiouun", strict=True)),
    "\N{COMBINING ACUTE ACCENT}": "",
    "\N{COMBINING TILDE}": "",
    "\N{COMBINING DIAERESIS}": "",
}
TITLE_SEARCH_TRANSLATION = str.maketrans(TITLE_SEARCH_REPLACEMENTS)


@require_http_methods(["GET", "HEAD", "POST"])
def index(request):
    if request.method == "POST":
        query = request.POST.get("search", "").strip()[:100]
        return redirect(f"{reverse('home')}?{urlencode({'search': query})}")
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

    page = Paginator(results, 24).get_page(request.GET.get("page"))
    return render(
        request,
        "index.html",
        {
            "videos": page.object_list,
            "page": page,
            "query": query,
        },
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
def play_(request, id):
    video = get_object_or_404(Videos, pk=id)
    if not video.video:
        raise Http404
    if request.method == "GET":
        Videos.objects.filter(pk=video.pk).update(visitas=F("visitas") + 1)
    return render(
        request, "play.html", {"video": video, "recommended_videos": video_recommendations(video)}
    )


@require_safe
def redirect_(request):
    return render(request, "redirect.html", {"public_base_url": settings.PUBLIC_BASE_URL})
