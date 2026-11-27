import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import URLValidator
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
env_file = ".env.production" if os.getenv("DJANGO_ENV") == "production" else ".env"
load_dotenv(BASE_DIR / env_file)


def required_env(name, legacy_name=None):
    value = os.getenv(name)
    if not value and legacy_name:
        value = os.getenv(legacy_name)
    if not value or not value.strip():
        raise ImproperlyConfigured(f"Define {name} en el entorno de SoplaX.")
    return value


def env_list(name, default=""):
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


ENVIRONMENT = os.getenv("DJANGO_ENV", "production")
if ENVIRONMENT not in {"development", "production"}:
    raise ImproperlyConfigured("DJANGO_ENV debe ser development o production.")
DEVELOPMENT = ENVIRONMENT == "development"
DEBUG = DEVELOPMENT

PLAY_AD_PREVIEW = DEVELOPMENT and os.getenv("SOPLAX_PLAY_AD_PREVIEW") == "1"
try:
    PLAY_ADS = json.loads(os.getenv("SOPLAX_PLAY_ADS", "{}"))
except (ValueError, RecursionError):
    PLAY_ADS = {}
if not isinstance(PLAY_ADS, dict):
    PLAY_ADS = {}

SECRET_KEY = required_env("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY debe ser una clave aleatoria de al menos 50 caracteres.")
SECRET_KEY_FALLBACKS = []

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if DEVELOPMENT else "")
if not ALLOWED_HOSTS or any(
    not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*|\[[0-9a-fA-F:]+\]", host)
    for host in ALLOWED_HOSTS
):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS debe enumerar los dominios permitidos.")

PUBLIC_BASE_URL = os.getenv("DJANGO_PUBLIC_BASE_URL", "http://127.0.0.1:8000" if DEVELOPMENT else "")
try:
    public_url = urlsplit(PUBLIC_BASE_URL)
    URLValidator(schemes=["http", "https"] if DEVELOPMENT else ["https"])(PUBLIC_BASE_URL)
    public_host = f"[{public_url.hostname}]" if ":" in (public_url.hostname or "") else public_url.hostname
    if (
        public_host not in {host.lower() for host in ALLOWED_HOSTS}
        or public_url.username is not None
        or public_url.path not in {"", "/"}
        or public_url.query
        or public_url.fragment
    ):
        raise ValueError("Invalid public origin")
except (ValueError, ValidationError) as error:
    raise ImproperlyConfigured("DJANGO_PUBLIC_BASE_URL debe ser un origen permitido.") from error
PUBLIC_BASE_URL = f"{public_url.scheme}://{public_url.netloc}"
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

AUTH_USER_MODEL = "app.Usuario"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"
PASSWORD_RESET_TIMEOUT = 30 * 60
REGISTRATION_LINK_TIMEOUT = 30 * 60

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "app.middleware.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "app.middleware.AuthThrottleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "project.urls"
WSGI_APPLICATION = "project.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440
MEDIA_ORIGIN = ""

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEVELOPMENT
CSRF_COOKIE_SECURE = not DEVELOPMENT
SECURE_SSL_REDIRECT = not DEVELOPMENT
SECURE_HSTS_SECONDS = 0 if DEVELOPMENT else int(os.getenv("DJANGO_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEVELOPMENT and os.getenv("DJANGO_HSTS_INCLUDE_SUBDOMAINS") == "1"
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

TRUST_PROXY = not DEVELOPMENT and os.getenv("DJANGO_TRUST_PROXY") == "1"
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

RATELIMIT_IP_META_KEY = "app.middleware.client_ip"
RATELIMIT_FAIL_OPEN = False

if DEVELOPMENT:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("DJANGO_SQLITE_PATH") or BASE_DIR / "db.sqlite3",
        }
    }
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "soplax@localhost"
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": required_env("DB_NAME"),
            "USER": required_env("DB_USER", "DB_NAME"),
            "PASSWORD": required_env("DB_PASSWORD"),
            "HOST": required_env("DB_HOST"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "OPTIONS": {},
        }
    }
    if db_ssl_ca := os.getenv("DB_SSL_CA"):
        DATABASES["default"]["OPTIONS"].update(sslmode="verify-full", sslrootcert=db_ssl_ca)

if not DEVELOPMENT or os.getenv("DJANGO_USE_S3") == "1":
    INSTALLED_APPS.append("storages")
    bucket = required_env("AWS_STORAGE_BUCKET_NAME")
    region = required_env("AWS_S3_REGION_NAME")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or not re.fullmatch(
        r"[a-z]+(?:-[a-z0-9]+)+-\d+", region
    ):
        raise ImproperlyConfigured("Configura un bucket y una región válidos de Amazon S3.")
    aws_domain = "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com"
    s3_host = f"s3.{region}.{aws_domain}"
    path_style = "." in bucket
    MEDIA_ORIGIN = f"https://{s3_host if path_style else f'{bucket}.{s3_host}'}"
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": bucket,
                "region_name": region,
                "endpoint_url": f"https://{s3_host}",
                "addressing_style": "path" if path_style else "virtual",
                "signature_version": "s3v4",
                "default_acl": None,
                "file_overwrite": False,
                "querystring_auth": True,
                "querystring_expire": 3600,
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

if not DEVELOPMENT:
    INSTALLED_APPS += ["django_ratelimit", "django_rq"]
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = required_env("EMAIL_HOST", "STMPURL")
    EMAIL_HOST_USER = required_env("EMAIL_HOST_USER", "SENDER_EMAIL_ADDRESS")
    EMAIL_HOST_PASSWORD = required_env("EMAIL_HOST_PASSWORD", "EMAIL_PASSWORD")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = True
    EMAIL_TIMEOUT = 8
    DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER

    redis_url = required_env("REDIS_URL")
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": redis_url,
            "KEY_PREFIX": "soplax",
            "OPTIONS": {
                "SERIALIZER": "django_redis.serializers.json.JSONSerializer",
                "SOCKET_CONNECT_TIMEOUT": 2,
                "SOCKET_TIMEOUT": 2,
            },
        },
    }
    RQ_QUEUES = {
        "account_mail": {
            "URL": redis_url,
            "SERIALIZER": "rq.serializers.JSONSerializer",
            "DEFAULT_TIMEOUT": 20,
        },
    }
