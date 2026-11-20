import hashlib
import logging
import secrets
from datetime import timedelta
from smtplib import SMTPException

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import RegistroPendiente, Usuario


logger = logging.getLogger(__name__)


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def queue_account_email(task, email):
    if settings.DEVELOPMENT:
        task(email)
        return
    import django_rq

    queue = django_rq.get_queue("account_mail", commit_mode="auto")
    queue.enqueue(
        task,
        email,
        description=task.__name__,
        ttl=300,
        result_ttl=0,
        failure_ttl=300,
    )


def deliver_link(email, subject, explanation, route, **kwargs):
    link = settings.PUBLIC_BASE_URL + reverse(route, kwargs=kwargs)
    body = f"{explanation}\n\n{link}\n\nSi no hiciste esta solicitud, puedes ignorar este mensaje.\n"
    try:
        send_mail(subject, body, None, [email])
    except (SMTPException, OSError):
        logger.warning("No se pudo entregar un correo de cuenta.")
        return False
    return True


def send_registration_email(email):
    if Usuario.objects.filter(email=email).exists():
        return

    token = secrets.token_urlsafe(32)
    registration = RegistroPendiente.objects.create(
        token_hash=token_digest(token),
        email=email,
        expires_at=timezone.now() + timedelta(seconds=settings.REGISTRATION_LINK_TIMEOUT),
    )
    delivered = deliver_link(
        email,
        "SoplaX — Confirma tu correo",
        "Confirma tu correo y completa el registro. El enlace vence en 30 minutos.",
        "register_token",
        token=token,
    )
    if not delivered:
        registration.delete()


def send_password_reset_email(email):
    user = next(PasswordResetForm().get_users(email), None)
    if user is None or user.email != email:
        return
    deliver_link(
        user.email,
        "SoplaX — Restablece tu contraseña",
        "Usa este enlace para cambiar tu contraseña. El enlace vence en 30 minutos.",
        "password_reset_confirm",
        uidb64=urlsafe_base64_encode(force_bytes(user.pk)),
        token=default_token_generator.make_token(user),
    )
