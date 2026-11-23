from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from oauth2_provider.decorators import protected_resource


def build_oauth_userinfo_payload(user) -> dict:
    """Return stable identity and status claims for OAuth2 clients (e.g. Misago)."""
    email = (getattr(user, "email", "") or "").strip()
    email_verified = bool(email and getattr(user, "email_verified", False))
    return {
        "id": str(user.pk),
        "sub": str(user.pk),
        "username": user.username,
        "name": user.username,
        "email": email,
        "email_verified": email_verified,
        "participant_status": getattr(user, "participant_status", "pending"),
        "is_collaborator": bool(getattr(user, "is_collaborator", False)),
        "is_staff": bool(getattr(user, "is_staff", False)),
    }


@never_cache
@require_http_methods(["GET"])
@protected_resource(scopes=["read"])
def userinfo(request):
    """OAuth2 Bearer-protected profile endpoint for Misago user_data_url."""
    owner = getattr(request, "resource_owner", None)
    if owner is None or not getattr(owner, "is_authenticated", False) or not owner.is_active:
        return JsonResponse({"error": "invalid_user"}, status=401)
    return JsonResponse(build_oauth_userinfo_payload(owner))
