from django.conf import global_settings

from . import settings as base
from .settings import *


ROOT_URLCONF = "project.urls_docker"
MIDDLEWARE = [MIDDLEWARE[0], "whitenoise.middleware.WhiteNoiseMiddleware", *MIDDLEWARE[1:]]
STORAGES = {
    **getattr(base, "STORAGES", global_settings.STORAGES),
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
