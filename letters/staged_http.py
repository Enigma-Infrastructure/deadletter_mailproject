"""Staged HTTP adapters for domain presentation and token-checked editing.

These views are NOT wired to the live project URL configuration. They exist
only for isolated integration testing. They wrap existing domain services
without reimplementing them.

Error responses are generic: no raw SQL, secrets, content, or exception
traces are exposed.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .domain_editing import (
    DraftConflict,
    letter_draft_snapshot,
    request_draft_snapshot,
    save_letter_draft,
    save_request_draft,
)
from .domain_presentation import (
    letter_card,
    letter_cards,
    letter_draft_card,
    request_card,
    request_cards,
    request_draft_card,
)


def _error_response(message, status=400):
    """Generic error response without leaking internals."""
    return JsonResponse({"error": message}, status=status)


def _parse_limit(value, default=20):
    """Parse a bounded integer limit from query params."""
    if value is None:
        return default
    try:
        limit = int(value)
    except (ValueError, TypeError):
        raise ValidationError("The result limit must be an integer from 1 to 100.")
    if not 1 <= limit <= 100:
        raise ValidationError("The result limit must be an integer from 1 to 100.")
    return limit


# --------------------------------------------------
# Audience list/detail (GET only)
# --------------------------------------------------

@require_GET
def staged_request_list(request):
    """GET audience-visible request cards using the presentation allowlist."""
    try:
        limit = _parse_limit(request.GET.get("limit"))
        cards = request_cards(request.user, limit=limit)
    except ValidationError as exc:
        return _error_response(str(exc.messages[0]))
    return JsonResponse({"cards": cards})


@require_GET
def staged_request_detail(request, request_id):
    """GET a single audience-visible request card."""
    try:
        identifier = int(request_id)
    except (ValueError, TypeError):
        return _error_response("A positive integer record identifier is required.")
    card = request_card(request.user, identifier)
    if card is None:
        return _error_response("This request is not available.", status=404)
    return JsonResponse({"card": card})


@require_GET
def staged_letter_list(request):
    """GET audience-visible letter cards using the presentation allowlist."""
    try:
        limit = _parse_limit(request.GET.get("limit"))
        cards = letter_cards(request.user, limit=limit)
    except ValidationError as exc:
        return _error_response(str(exc.messages[0]))
    return JsonResponse({"cards": cards})


@require_GET
def staged_letter_detail(request, letter_id):
    """GET a single audience-visible letter card."""
    try:
        identifier = int(letter_id)
    except (ValueError, TypeError):
        return _error_response("A positive integer record identifier is required.")
    card = letter_card(request.user, identifier)
    if card is None:
        return _error_response("This letter is not available.", status=404)
    return JsonResponse({"card": card})


# --------------------------------------------------
# Private draft snapshot (GET only, approved owner/writer)
# --------------------------------------------------

@require_GET
def staged_request_draft_snapshot(request, request_id):
    """GET a private request draft snapshot with edit token."""
    try:
        identifier = int(request_id)
    except (ValueError, TypeError):
        return _error_response("A positive integer record identifier is required.")
    try:
        envelope = request_draft_snapshot(request.user, identifier)
    except PermissionDenied:
        return _error_response("This draft is unavailable.", status=403)
    except ValidationError as exc:
        return _error_response(str(exc.messages[0]))
    return JsonResponse(envelope)


@require_GET
def staged_letter_draft_snapshot(request, letter_id):
    """GET a private letter draft snapshot with edit token."""
    try:
        identifier = int(letter_id)
    except (ValueError, TypeError):
        return _error_response("A positive integer record identifier is required.")
    try:
        envelope = letter_draft_snapshot(request.user, identifier)
    except PermissionDenied:
        return _error_response("This draft is unavailable.", status=403)
    except ValidationError as exc:
        return _error_response(str(exc.messages[0]))
    return JsonResponse(envelope)


# --------------------------------------------------
# Token-checked draft saves (POST only, CSRF protected)
# --------------------------------------------------

@csrf_protect
@require_POST
def staged_request_draft_save(request, request_id):
    """POST a token-checked request draft save."""
    try:
        identifier = int(request_id)
    except (ValueError, TypeError):
        return _error_response("A positive integer record identifier is required.")

    # Strict input allowlist: only prompt and requested_visibility.
    prompt = request.POST.get("prompt")
    requested_visibility = request.POST.get("requested_visibility")
    expected_token = request.POST.get("expected_token")

    if expected_token is None:
        return _error_response("An expected edit token is required.")

    try:
        envelope = save_request_draft(
            request.user,
            request_id=identifier,
            expected_token=expected_token,
            prompt=prompt,
            requested_visibility=requested_visibility,
        )
    except PermissionDenied:
        return _error_response("This draft is unavailable.", status=403)
    except DraftConflict:
        return _error_response(
            "The draft state is stale or the edit token is invalid/expired. Reload before saving.",
            status=409,
        )
    except ValidationError as exc:
        return _error_response(str(exc.messages[0]))
    except Exception:
        return _error_response("A database error occurred. No changes were made.", status=500)
    return JsonResponse(envelope)


@csrf_protect
@require_POST
def staged_letter_draft_save(request, letter_id):
    """POST a token-checked letter draft save."""
    try:
        identifier = int(letter_id)
    except (ValueError, TypeError):
        return _error_response("A positive integer record identifier is required.")

    # Strict input allowlist: only body_text and requested_visibility.
    body_text = request.POST.get("body_text")
    requested_visibility = request.POST.get("requested_visibility")
    expected_token = request.POST.get("expected_token")

    if expected_token is None:
        return _error_response("An expected edit token is required.")

    try:
        envelope = save_letter_draft(
            request.user,
            letter_id=identifier,
            expected_token=expected_token,
            body_text=body_text,
            requested_visibility=requested_visibility,
        )
    except PermissionDenied:
        return _error_response("This draft is unavailable.", status=403)
    except DraftConflict:
        return _error_response(
            "The draft state is stale or the edit token is invalid/expired. Reload before saving.",
            status=409,
        )
    except ValidationError as exc:
        return _error_response(str(exc.messages[0]))
    except Exception:
        return _error_response("A database error occurred. No changes were made.", status=500)
    return JsonResponse(envelope)
