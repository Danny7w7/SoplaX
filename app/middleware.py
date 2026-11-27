from ipaddress import ip_address

from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import patch_cache_control
from django_ratelimit.core import is_ratelimited
from redis.exceptions import RedisError


def client_ip(request):
    address = request.META.get("REMOTE_ADDR", "")
    if settings.TRUST_PROXY:
        try:
            return str(ip_address(request.META.get("HTTP_X_REAL_IP", "")))
        except ValueError:
            pass
    return address


def auth_service_unavailable():
    return HttpResponse(
        "El servicio de cuentas no está disponible temporalmente.",
        status=503,
        headers={"Cache-Control": "no-store"},
    )


class AuthThrottleMiddleware:
    rates = {
        "login": "10/m",
        "admin:login": "10/m",
        "register": "5/15m",
        "recover": "5/15m",
        "register_confirm": "10/m",
        "password_reset_confirm": "10/m",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        route = request.resolver_match.view_name
        rate = self.rates.get(route)
        if request.method != "POST" or rate is None:
            return None
        try:
            limited = is_ratelimited(request, group=route, key="ip", rate=rate, increment=True)
        except RedisError:
            return auth_service_unavailable()
        if limited:
            return HttpResponse(
                "Demasiadas solicitudes. Inténtalo más tarde.",
                status=429,
                headers={"Cache-Control": "no-store"},
            )
        return None


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        media = f" {settings.MEDIA_ORIGIN}" if settings.MEDIA_ORIGIN else ""
        self.policy = "; ".join(
            [
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
                "font-src 'self' https://fonts.gstatic.com",
                f"img-src 'self' data: https://cdn-icons-png.flaticon.com{media}",
                f"media-src 'self'{media}",
                "base-uri 'none'",
                "object-src 'none'",
                "frame-src 'none'",
                "frame-ancestors 'none'",
                "form-action 'self'",
            ]
        )

    def __call__(self, request):
        response = self.get_response(request)
        if response.headers.get("Content-Type", "").split(";", 1)[0] == "text/html":
            response.headers["Content-Security-Policy"] = self.policy
            patch_cache_control(response, private=True, no_store=True)
        return response
