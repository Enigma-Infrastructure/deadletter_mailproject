"""Read-only selectors exposing spacemarches summaries for core Deadletter Mail templates."""
from __future__ import annotations

from typing import Any

from .models import AgentSaveSlot, CharacterDossier, DiscordLink, EclipsePhaseCensus, FieldAgent, GeneratedCharacter


def get_user_spacemarches_summary(user) -> dict[str, Any]:
    """
    Return a safe, template-ready summary dict for a user's Spacemarches state:
    active dossiers, generated characters, agent clearance summary, and unlocked logs.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return {
            "authenticated": False,
            "active_dossiers": [],
            "dossier_count": 0,
            "active_censuses": [],
            "census_count": 0,
            "generated_characters": [],
            "generated_character_count": 0,
            "clearance_summary": {},
            "unlocked_logs": [],
            "save_slots_count": 0,
            "discord_linked": False,
        }

    dossiers_qs = CharacterDossier.objects.filter(user=user).order_by("-updated_at")
    active_dossiers = []
    for dossier in dossiers_qs[:5]:
        responses = dossier.responses if isinstance(dossier.responses, dict) else {}
        answered_count = sum(
            1
            for val in responses.values()
            if isinstance(val, dict) and str(val.get("answer", "")).strip()
        )
        active_dossiers.append(
            {
                "character_name": dossier.character_name,
                "slug": dossier.slug,
                "narrative_voice": dossier.narrative_voice,
                "answered_count": answered_count,
                "updated_at": dossier.updated_at,
            }
        )

    save_slots = list(AgentSaveSlot.objects.filter(user=user).order_by("-updated_at")[:5])
    clearance_summary: dict[str, Any] = {}
    unlocked_logs: list[str] = []

    if save_slots:
        latest_slot = save_slots[0]
        if isinstance(latest_slot.clearance_summary, dict):
            clearance_summary = dict(latest_slot.clearance_summary)
        raw_state = latest_slot.raw_state if isinstance(latest_slot.raw_state, dict) else {}
        slot_logs = clearance_summary.get("unlocked_logs") or raw_state.get("unlocked_logs") or []
        if isinstance(slot_logs, list):
            for entry in slot_logs:
                entry_str = str(entry).strip()
                if entry_str and entry_str not in unlocked_logs:
                    unlocked_logs.append(entry_str)

    field_agents = list(
        FieldAgent.objects.filter(user=user).select_related("campaign").order_by("-joined_at")[:5]
    )
    if field_agents:
        clearance_summary.setdefault(
            "field_assignments",
            [
                {
                    "callsign": agent.callsign,
                    "clearance_level": agent.clearance_level,
                    "campaign": agent.campaign.title or agent.campaign.story_slug,
                }
                for agent in field_agents
            ],
        )

    discord_link = DiscordLink.objects.filter(user=user).first()
    discord_linked = bool(discord_link and discord_link.discord_user_id)

    censuses_qs = EclipsePhaseCensus.objects.filter(user=user).order_by("-updated_at")
    active_censuses = []
    for census in censuses_qs[:5]:
        c_responses = census.responses if isinstance(census.responses, dict) else {}
        c_answered = sum(
            1
            for val in c_responses.values()
            if isinstance(val, dict) and str(val.get("answer", "")).strip()
        )
        active_censuses.append(
            {
                "id": census.pk,
                "character_name": census.character_name,
                "slug": census.slug,
                "answered_count": c_answered,
                "updated_at": census.updated_at,
            }
        )

    gen_qs = GeneratedCharacter.objects.filter(user=user).select_related("dossier").order_by("-updated_at")
    generated_characters = [
        {
            "id": gc.pk,
            "character_name": gc.character_name,
            "source_system": gc.source_system,
            "dossier_slug": gc.dossier.slug if gc.dossier_id and gc.dossier else None,
            "dossier_name": gc.dossier.character_name if gc.dossier_id and gc.dossier else None,
            "updated_at": gc.updated_at,
        }
        for gc in gen_qs[:5]
    ]

    return {
        "authenticated": True,
        "active_dossiers": active_dossiers,
        "dossier_count": dossiers_qs.count(),
        "active_censuses": active_censuses,
        "census_count": censuses_qs.count(),
        "generated_characters": generated_characters,
        "generated_character_count": gen_qs.count(),
        "clearance_summary": clearance_summary,
        "unlocked_logs": unlocked_logs,
        "save_slots_count": AgentSaveSlot.objects.filter(user=user).count(),
        "discord_linked": discord_linked,
    }
