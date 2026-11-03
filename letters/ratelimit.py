"""Shared account-aware rate limiting utility.

Supports IP-based rate limiting for anonymous visitors and account-based rate limiting
for authenticated users. Uses Django cache backend.
"""
from django.core.cache import cache
from django.http import HttpResponse


def get_client_ip(request) -> str:
    """Retrieve client IP address, handling proxy headers if configured."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "").strip()
    return ip or "127.0.0.1"


def check_rate_limit(request, action: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    """Check and increment request count for rate limiting.

    Returns True if the request is permitted, False if limit is exceeded.
    """
    if getattr(request, "user", None) and request.user.is_authenticated:
        cache_key = f"rl:{action}:user:{request.user.pk}"
    else:
        ip = get_client_ip(request)
        cache_key = f"rl:{action}:ip:{ip}"

    count = cache.get(cache_key, 0)
    if count >= max_requests:
        return False

    cache.set(cache_key, count + 1, window_seconds)
    return True


def rate_limit_response(retry_after: int = 60) -> HttpResponse:
    """Standard HTTP 429 response when rate limit is exceeded."""
    response = HttpResponse(
        "Too many requests. Please wait a moment before trying again.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"] = str(retry_after)
    return response
