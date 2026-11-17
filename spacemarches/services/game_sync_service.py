"""Cloud save synchronization service for the incoming mesh-net runtime."""
from __future__ import annotations

from typing import Any

from django.db import transaction

from spacemarches.models import AgentSaveSlot


def _normalize_slot_name(slot_name: str | None) -> str:
    cleaned = (slot_name or "auto").strip()
    if not cleaned:
        return "auto"
    return cleaned[:64]


def sync_agent_save(
    user,
    slot_name: str = "auto",
    raw_state: dict[str, Any] | None = None,
    clearance_summary: dict[str, Any] | None = None,
) -> tuple[AgentSaveSlot, bool]:
    """Persist or update a user's mesh-net state snapshot atomically."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required to sync agent save state.")

    state_payload = {} if raw_state is None else raw_state
    summary_payload = {} if clearance_summary is None else clearance_summary

    if not isinstance(state_payload, dict):
        raise ValueError("raw_state must be a JSON object.")
    if not isinstance(summary_payload, dict):
        raise ValueError("clearance_summary must be a JSON object.")

    normalized_slot = _normalize_slot_name(slot_name)
    with transaction.atomic():
        slot, created = AgentSaveSlot.objects.update_or_create(
            user=user,
            slot_name=normalized_slot,
            defaults={
                "raw_state": state_payload,
                "clearance_summary": summary_payload,
            },
        )
    return slot, created


def load_agent_save(user, slot_name: str = "auto") -> dict[str, Any]:
    """Load the persisted mesh-net state snapshot for a user and slot."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required to load agent save state.")

    normalized_slot = _normalize_slot_name(slot_name)
    slot = AgentSaveSlot.objects.filter(user=user, slot_name=normalized_slot).first()
    if slot is None:
        return {
            "exists": False,
            "slot_name": normalized_slot,
            "raw_state": {},
            "clearance_summary": {},
            "updated_at": None,
        }
    return {
        "exists": True,
        "slot_name": slot.slot_name,
        "raw_state": slot.raw_state if isinstance(slot.raw_state, dict) else {},
        "clearance_summary": slot.clearance_summary if isinstance(slot.clearance_summary, dict) else {},
        "updated_at": slot.updated_at.isoformat(),
    }
