"""Opt-in HTTPS production settings. Local settings.py remains unchanged."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


def _boolean(name, default=False):
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ImproperlyConfigured(f"{name} must be true or false.")
    return value in {"true", "1", "yes"}


def _absolute_path(name, default):
    value = Path(os.environ.get(name, str(default)))
    if not value.is_absolute():
        raise ImproperlyConfigured(f"{name} must be an absolute path.")
    return value


DEBUG = False
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if (len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5
        or SECRET_KEY.startswith("django-insecure-")):
    raise ImproperlyConfigured(
        "Production requires DJANGO_SECRET_KEY: at least 50 characters, "
        "at least 5 distinct characters, and no django-insecure- prefix."
    )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
if not ALLOWED_HOSTS or any(
    "*" in host or "://" in host or "/" in host or host.startswith(".")
    or any(character.isspace() for character in host)
    for host in ALLOWED_HOSTS
):
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must contain explicit comma-separated hostnames "
        "or IP addresses, without schemes, paths, or wildcard domains."
    )

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Opt in only when a trusted proxy overwrites this header and direct backend
# access is blocked. Never trust an arbitrary client's forwarded headers.
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if _boolean("DJANGO_TRUST_PROXY_HTTPS") else None
)
USE_X_FORWARDED_HOST = False

def _integer(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer.")


# HTTP Strict Transport Security (HSTS)
# Default to 31536000 seconds (1 year) for production SSL.
SECURE_HSTS_SECONDS = _integer("DJANGO_SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _boolean("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = _boolean("DJANGO_SECURE_HSTS_PRELOAD", False)

SILENCED_SYSTEM_CHECKS = []
if not SECURE_HSTS_PRELOAD:
    SILENCED_SYSTEM_CHECKS.append("security.W021")

STATIC_ROOT = _absolute_path("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles")
MEDIA_ROOT = _absolute_path("DJANGO_MEDIA_ROOT", BASE_DIR / "media")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _absolute_path("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
    }
}
