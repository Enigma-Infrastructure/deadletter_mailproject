"""Secret / ST-only protection primitives for sheets and dossiers.

The model:
- ``protection`` is ``none`` | ``secret`` | ``st_only``.
- ``secret`` locks the section for everyone (including the owner) until the
  viewer enters the puzzle answer. Verification happens server-side via
  ``check_password``; the answer hash never leaves the server.
- ``st_only`` requires a logged-in Storyteller (``is_st``). Every view is
  logged to ``ProtectionAccessLog`` — the Eclipse Phase-themed security log.
- The owner can unlock via an "authenticate with credentials" action (enter
  their own cipher/answer); that is the only path that bypasses the lock.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from spacemarches.models import GeneratedCharacter, ProtectionAccessLog

# Session key mapping "kind:pk" -> unlocked timestamp marker.
SESSION_UNLOCKS = "protection_unlocks_v1"


def unlock_key(target_kind: str, target_pk: int) -> str:
    return f"{target_kind}:{target_pk}"


def set_secret(obj, puzzle_prompt: str, answer: str) -> None:
    """Set (or replace) the secret lock on obj. ``answer`` is hashed immediately.

    An empty ``answer`` keeps the existing hash (so the owner can edit the
    puzzle prompt without rotating the cipher). Pass an explicit new answer
    to rotate the cipher; callers that want to *clear* the cipher should
    use ``clear_secret``.
    """
    obj.secret_puzzle_prompt = (puzzle_prompt or "").strip()
    if answer:
        obj.secret_answer_hash = make_password(answer)
    obj.save(update_fields=["secret_puzzle_prompt", "secret_answer_hash"])


def verify_secret(obj, answer: str) -> bool:
    """Check the viewer's answer against the stored hash."""
    if not obj or not obj.secret_answer_hash:
        return False
    return check_password(answer or "", obj.secret_answer_hash)


def clear_secret(obj) -> None:
    obj.secret_puzzle_prompt = ""
    obj.secret_answer_hash = ""
    obj.save(update_fields=["secret_puzzle_prompt", "secret_answer_hash"])


def is_unlocked(request, target_kind: str, target_pk: int) -> bool:
    unlocks = (request.session.get(SESSION_UNLOCKS) or {}) if request is not None else {}
    return bool(unlocks.get(unlock_key(target_kind, target_pk)))


def mark_unlocked(request, target_kind: str, target_pk: int) -> None:
    if request is None:
        return
    unlocks = dict(request.session.get(SESSION_UNLOCKS) or {})
    unlocks[unlock_key(target_kind, target_pk)] = timezone.now().isoformat()
    request.session[SESSION_UNLOCKS] = unlocks


def protection_state(obj, request, viewer=None) -> dict[str, Any]:
    """Return the current protection state for ``obj`` as seen by ``viewer``.

    Shape: {protection, locked, unlocked, secret_puzzle_prompt, reason, is_owner}
    """
    if obj is None:
        return {"protection": "none", "locked": False, "unlocked": False, "secret_puzzle_prompt": "", "reason": "missing", "is_owner": False}

    protection = obj.protection or "none"
    is_owner = bool(viewer is not None and getattr(viewer, "is_authenticated", False) and getattr(obj, "user_id", None) == viewer.pk)

    if protection == GeneratedCharacter.PROTECTION_NONE:
        return {"protection": "none", "locked": False, "unlocked": True, "secret_puzzle_prompt": "", "reason": "", "is_owner": is_owner}

    if protection == GeneratedCharacter.PROTECTION_ST_ONLY:
        is_st = bool(viewer and getattr(viewer, "is_authenticated", False) and getattr(viewer, "is_st", False))
        if is_st:
            return {"protection": "st_only", "locked": False, "unlocked": True, "secret_puzzle_prompt": "", "reason": "", "is_owner": is_owner}
        return {"protection": "st_only", "locked": True, "unlocked": False, "secret_puzzle_prompt": "", "reason": "Storyteller accounts only.", "is_owner": is_owner}

    if protection == GeneratedCharacter.PROTECTION_SECRET:
        kind = getattr(obj, "PROTECTION_TARGET_KIND", None) or (
            "character" if isinstance(obj, GeneratedCharacter) else "dossier"
        )
        unlocked = is_unlocked(request, kind, obj.pk)
        if unlocked:
            return {"protection": "secret", "locked": False, "unlocked": True, "secret_puzzle_prompt": "", "reason": "", "is_owner": is_owner}
        return {"protection": "secret", "locked": True, "unlocked": False, "secret_puzzle_prompt": obj.secret_puzzle_prompt or "", "reason": "Sealed with a secret.", "is_owner": is_owner}

    return {"protection": "none", "locked": False, "unlocked": True, "secret_puzzle_prompt": "", "reason": "", "is_owner": is_owner}


def log_protection_access(*, target_kind: str, target_pk: int, owner, viewer, protection_type: str, note: str = ""):
    """Record a protection access event. Safe to call for any viewer.

    Entries are only meaningful for st_only/secret locks; the caller is
    expected to have already resolved the lock.
    """
    return ProtectionAccessLog.objects.create(
        target_kind=target_kind,
        target_pk=target_pk,
        owner=owner,
        viewer=viewer,
        protection_type=protection_type,
        note=note or "",
    )


def is_secret_unlockable(obj, viewer=None) -> bool:
    """True when the section is a secret lock (regardless of viewer)."""
    return bool(obj and obj.protection == GeneratedCharacter.PROTECTION_SECRET and obj.secret_answer_hash)
