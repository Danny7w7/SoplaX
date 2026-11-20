from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.urls import path
from django.views.decorators.http import require_safe

from .urls import urlpatterns as site_urlpatterns


@require_safe
def healthcheck(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return HttpResponse("unavailable\n", status=503, content_type="text/plain")
    return HttpResponse("ok\n", content_type="text/plain")


urlpatterns = [
    path("healthz/", healthcheck, name="healthcheck"),
    *site_urlpatterns,
]
