"""Cross-model synchronization and sheet-prompt helpers across Census, Dossier, and Point-Buy Sheets."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils.dateparse import parse_datetime

from spacemarches.models import CharacterDossier, EclipsePhaseCensus, GeneratedCharacter
from spacemarches.services.character_sync_service import extract_point_buy_summary

# Semantic 1:1 / close-overlap mapping between EclipsePhaseCensus IDs and CharacterDossier IDs.
# Mapped strictly by prompt meaning (the two schemas diverge on several question numbers).
CENSUS_TO_DOSSIER_MAP: dict[str, str] = {
    "1": "6.1g",    # How the Fall affected you / Fall survival
    "2": "2",       # Origin / coming into being / age & instantiation
    "3": "3",       # Current morph / sleeve
    "4": "8",       # Where you live / primary berth
    "5": "5",       # Primary occupation / specialty / cover
    "7": "6.2g",    # Contacts & reputation networks
    "11a": "12A",   # Morph physical silhouette, build, gender & mods
    "11b": "12C",   # Everyday attire & signature kit
    "11c": "6.1c",  # Family / creators / surviving lineage
    "11d": "6.1f",  # Prior occupations
    "11g": "11",    # Core personality & boundaries
    "11h": "11e",   # Moral red line / won't do
    "11j": "1",     # Legal name, birth designation & aliases
    "12": "6.2f",   # Relationship with your Muse
}

DOSSIER_TO_CENSUS_MAP: dict[str, str] = {
    dossier_qid: census_qid for census_qid, dossier_qid in CENSUS_TO_DOSSIER_MAP.items()
}

# Sheet-relevant narrative prompt IDs tracked for pending-sheet-update reminders
SHEET_TRACKED_CENSUS_IDS: dict[str, str] = {
    "2": "Background / Origin",
    "3": "Current Morph",
    "4": "Home / Habitat / Faction",
    "5": "Career / Occupation / Concept",
    "6": "Faction / Political Stance",
    "7": "Reputations",
    "10": "Motivations",
    "11a": "Morph Description / Gender",
    "11j": "Character Name / Aliases",
    "11k": "Faction / Citizenship",
    "12": "Muse",
    "13a": "Gender Identity",
}

SHEET_TRACKED_DOSSIER_IDS: dict[str, str] = {
    "1": "Character Name / Aliases",
    "2": "Origin / Instantiation",
    "3": "Current Morph",
    "4": "Background & Faction",
    "5": "Career / Specialty / Concept",
    "6.1f": "Prior Profession",
    "6.1j": "Past / Current Faction",
    "6.2f": "Muse",
    "6.2g": "Reputations",
    "8": "Home / Habitat",
    "9": "Motivations",
    "12A": "Morph Silhouette",
}


def sync_census_answer_to_dossier(
    census: EclipsePhaseCensus,
    question_id: str,
    answer_text: str,
) -> str | None:
    """Propagate a non-empty Census answer to the semantically matching Dossier prompt."""
    dossier_qid = CENSUS_TO_DOSSIER_MAP.get(str(question_id))
    cleaned = (answer_text or "").strip()
    if not dossier_qid or not census.dossier_id or not cleaned:
        return None
    dossier = census.dossier
    if dossier is None:
        return None

    from spacemarches.services.dossier_service import save_dossier_answer

    save_dossier_answer(
        dossier,
        question_id=dossier_qid,
        answer_text=cleaned,
        entry_kind="character_creation",
        source="census_sync",
        propagate=False,
    )
    return dossier_qid


def sync_dossier_answer_to_censuses(
    dossier: CharacterDossier,
    question_id: str,
    answer_text: str,
    *,
    is_gm_only: bool = False,
) -> list[int]:
    """Propagate a non-empty Dossier answer to linked EclipsePhaseCensus records."""
    census_qid = DOSSIER_TO_CENSUS_MAP.get(str(question_id))
    cleaned = (answer_text or "").strip()
    if not census_qid or not cleaned or is_gm_only:
        return []

    from spacemarches.services.census_service import save_census_answer

    synced_ids: list[int] = []
    for census in dossier.censuses.all():
        save_census_answer(
            census,
            census_qid,
            cleaned,
            propagate=False,
        )
        synced_ids.append(census.pk)
    return synced_ids


def backfill_linked_census_and_dossier(
    census: EclipsePhaseCensus,
    dossier: CharacterDossier | None = None,
) -> dict[str, int]:
    """Backfill any unanswered mapped prompts when linking or opening a Census + Dossier pair."""
    target_dossier = dossier or (census.dossier if census.dossier_id else None)
    if target_dossier is None:
        return {"to_census": 0, "to_dossier": 0}

    from spacemarches.services.census_service import save_census_answer
    from spacemarches.services.dossier_service import save_dossier_answer

    c_responses = census.responses if isinstance(census.responses, dict) else {}
    d_responses = target_dossier.responses if isinstance(target_dossier.responses, dict) else {}
    private_keys = set(target_dossier.private_keys or [])

    to_census = 0
    to_dossier = 0

    for c_qid, d_qid in CENSUS_TO_DOSSIER_MAP.items():
        c_rec = c_responses.get(c_qid)
        c_ans = str(c_rec.get("answer", "")).strip() if isinstance(c_rec, dict) else ""
        d_rec = d_responses.get(d_qid)
        d_ans = str(d_rec.get("answer", "")).strip() if isinstance(d_rec, dict) else ""

        if d_ans and not c_ans and d_qid not in private_keys:
            save_census_answer(census, c_qid, d_ans, propagate=False)
            to_census += 1
        elif c_ans and not d_ans:
            save_dossier_answer(
                target_dossier,
                question_id=d_qid,
                answer_text=c_ans,
                entry_kind="character_creation",
                source="census_sync",
                propagate=False,
            )
            to_dossier += 1

    return {"to_census": to_census, "to_dossier": to_dossier}


def get_primary_linked_character_for_census(census: EclipsePhaseCensus) -> GeneratedCharacter | None:
    """Resolve the linked GeneratedCharacter directly or via linked Dossier."""
    if census.character_id and census.character is not None:
        return census.character
    if census.dossier_id and census.dossier is not None:
        return census.dossier.generated_characters.order_by("-updated_at").first()
    return None


def get_primary_linked_character_for_dossier(dossier: CharacterDossier) -> GeneratedCharacter | None:
    return dossier.generated_characters.order_by("-updated_at").first()


def build_sheet_prompt_context(character: GeneratedCharacter | None) -> dict[str, Any] | None:
    """Build normalized sheet field context for inline Census/Dossier reminders and editing."""
    if character is None:
        return None
    raw_data = character.raw_data if isinstance(character.raw_data, dict) else {}
    computed = extract_point_buy_summary(raw_data) if raw_data else {}
    stored = character.summary if isinstance(character.summary, dict) else {}

    def _pick(key: str, default: Any = "") -> Any:
        val = computed.get(key)
        if val not in (None, "", [], {}):
            return val
        return stored.get(key, default)

    skill_packs = _pick("skill_packs", {}) or {}
    morphs = _pick("morphs", []) or []
    reputations = _pick("reputations", {}) or {}
    motivations = _pick("motivations", []) or []
    languages = _pick("languages", []) or []
    traits = _pick("traits", []) or []
    sleights = _pick("sleights", []) or []

    ctx = {
        "id": character.pk,
        "character_name": character.character_name or _pick("character_name", ""),
        "full_name": _pick("full_name", ""),
        "concept": _pick("concept", ""),
        "ego_type": _pick("ego_type", ""),
        "gender": _pick("gender", ""),
        "muse_name": _pick("muse_name", ""),
        "description": _pick("description", ""),
        "background": skill_packs.get("background", ""),
        "career": skill_packs.get("career", ""),
        "interest": skill_packs.get("interest", ""),
        "faction": skill_packs.get("faction", ""),
        "morphs": list(morphs),
        "morphs_display": ", ".join(str(m) for m in morphs if m),
        "reputations": dict(reputations),
        "reputations_display": ", ".join(f"{k}: {v}" for k, v in reputations.items()),
        "motivations": list(motivations),
        "motivations_display": "; ".join(str(m) for m in motivations if m),
        "languages": list(languages),
        "traits": list(traits),
        "sleights": list(sleights),
    }
    return ctx


def get_census_question_sheet_hint(question_id: str, sheet_ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return sheet reminders and editable sheet field keys for a given Census prompt."""
    if not sheet_ctx:
        return None

    qid = str(question_id)
    reminders: list[tuple[str, str]] = []
    editable: list[str] = []

    if qid == "11j":
        if sheet_ctx.get("character_name"):
            reminders.append(("Sheet Name", sheet_ctx["character_name"]))
        if sheet_ctx.get("full_name"):
            reminders.append(("Full Name", sheet_ctx["full_name"]))
        editable = ["character_name", "full_name"]
    elif qid == "2":
        if sheet_ctx.get("background"):
            reminders.append(("Background", sheet_ctx["background"]))
        if sheet_ctx.get("ego_type"):
            reminders.append(("Ego Type", sheet_ctx["ego_type"]))
        editable = ["background", "ego_type"]
    elif qid in ("3", "11a"):
        if sheet_ctx.get("morphs_display"):
            reminders.append(("Morph", sheet_ctx["morphs_display"]))
        if qid == "11a" and sheet_ctx.get("gender"):
            reminders.append(("Gender", sheet_ctx["gender"]))
            editable = ["gender"]
    elif qid in ("4", "6", "11k") or qid.startswith("6.1"):
        if sheet_ctx.get("faction"):
            reminders.append(("Faction", sheet_ctx["faction"]))
        if qid == "4" and sheet_ctx.get("background"):
            reminders.append(("Background", sheet_ctx["background"]))
        if qid in ("4", "6", "11k"):
            editable = ["faction", "background"] if qid == "4" else ["faction"]
    elif qid in ("5", "11d"):
        if sheet_ctx.get("concept"):
            reminders.append(("Concept", sheet_ctx["concept"]))
        if sheet_ctx.get("career"):
            reminders.append(("Career", sheet_ctx["career"]))
        if sheet_ctx.get("interest"):
            reminders.append(("Interest", sheet_ctx["interest"]))
        if qid == "5":
            editable = ["concept", "career", "interest"]
    elif qid == "7":
        if sheet_ctx.get("reputations_display"):
            reminders.append(("Reputations", sheet_ctx["reputations_display"]))
    elif qid in ("10", "11u"):
        if sheet_ctx.get("motivations_display"):
            reminders.append(("Motivations", sheet_ctx["motivations_display"]))
    elif qid == "12" or qid.startswith("12"):
        if sheet_ctx.get("muse_name"):
            reminders.append(("Muse", sheet_ctx["muse_name"]))
        if qid == "12":
            editable = ["muse_name"]
    elif qid in ("13a", "13b"):
        if sheet_ctx.get("gender"):
            reminders.append(("Gender", sheet_ctx["gender"]))
        if qid == "13a":
            editable = ["gender"]
    elif qid == "6.2o":
        if sheet_ctx.get("sleights"):
            reminders.append(("Psi Sleights", ", ".join(sheet_ctx["sleights"])))

    if not reminders and not editable:
        return None
    return {"reminders": reminders, "editable_fields": editable}


def get_dossier_question_sheet_hint(question_id: str, sheet_ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return sheet reminders and editable sheet field keys for a given Dossier prompt."""
    if not sheet_ctx:
        return None

    qid = str(question_id)
    reminders: list[tuple[str, str]] = []
    editable: list[str] = []

    if qid == "1":
        if sheet_ctx.get("character_name"):
            reminders.append(("Sheet Name", sheet_ctx["character_name"]))
        if sheet_ctx.get("full_name"):
            reminders.append(("Full Name", sheet_ctx["full_name"]))
        editable = ["character_name", "full_name"]
    elif qid == "2":
        if sheet_ctx.get("ego_type"):
            reminders.append(("Ego Type", sheet_ctx["ego_type"]))
        if sheet_ctx.get("background"):
            reminders.append(("Background", sheet_ctx["background"]))
        editable = ["background", "ego_type"]
    elif qid in ("3", "12A"):
        if sheet_ctx.get("morphs_display"):
            reminders.append(("Morph", sheet_ctx["morphs_display"]))
    elif qid in ("4", "6.1j", "8"):
        if sheet_ctx.get("background"):
            reminders.append(("Background", sheet_ctx["background"]))
        if sheet_ctx.get("faction"):
            reminders.append(("Faction", sheet_ctx["faction"]))
        if qid in ("4", "8"):
            editable = ["faction", "background"]
    elif qid in ("5", "6.1f"):
        if sheet_ctx.get("concept"):
            reminders.append(("Concept", sheet_ctx["concept"]))
        if sheet_ctx.get("career"):
            reminders.append(("Career", sheet_ctx["career"]))
        if sheet_ctx.get("interest"):
            reminders.append(("Interest", sheet_ctx["interest"]))
        if qid == "5":
            editable = ["concept", "career", "interest"]
    elif qid == "6.2f":
        if sheet_ctx.get("muse_name"):
            reminders.append(("Muse", sheet_ctx["muse_name"]))
        editable = ["muse_name"]
    elif qid == "6.2g":
        if sheet_ctx.get("reputations_display"):
            reminders.append(("Reputations", sheet_ctx["reputations_display"]))
    elif qid in ("9", "11a"):
        if sheet_ctx.get("motivations_display"):
            reminders.append(("Motivations", sheet_ctx["motivations_display"]))
    elif qid == "6.2b":
        if sheet_ctx.get("traits"):
            reminders.append(("Ego Traits", ", ".join(sheet_ctx["traits"])))

    if not reminders and not editable:
        return None
    return {"reminders": reminders, "editable_fields": editable}


def _parse_iso_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return parse_datetime(value.strip())


def compute_pending_sheet_changes(
    character: GeneratedCharacter | None,
    *,
    dossier: CharacterDossier | None = None,
    census: EclipsePhaseCensus | None = None,
) -> dict[str, Any]:
    """Detect newer Census/Dossier updates or name drift that have not yet been synced to the Sheet."""
    empty = {"has_pending": False, "count": 0, "items": [], "suggested_name": ""}
    if character is None:
        return empty

    raw_data = character.raw_data if isinstance(character.raw_data, dict) else {}
    sync_meta = raw_data.get("spacemarchesSync") if isinstance(raw_data.get("spacemarchesSync"), dict) else {}
    ack_dt = _parse_iso_dt(sync_meta.get("acknowledged_at"))
    baseline_dt = character.updated_at
    if ack_dt is not None and (baseline_dt is None or ack_dt > baseline_dt):
        baseline_dt = ack_dt

    items: list[dict[str, str]] = []
    suggested_name = ""

    target_dossier = dossier or (character.dossier if character.dossier_id else None)
    censuses: list[EclipsePhaseCensus] = []
    if census is not None:
        censuses.append(census)
    else:
        censuses.extend(list(character.censuses.all()))
        if target_dossier is not None:
            seen_ids = {c.pk for c in censuses}
            for c in target_dossier.censuses.all():
                if c.pk not in seen_ids:
                    censuses.append(c)

    if target_dossier is not None:
        if (
            target_dossier.character_name
            and target_dossier.character_name.strip() != character.character_name.strip()
            and (baseline_dt is None or target_dossier.updated_at > baseline_dt)
        ):
            suggested_name = target_dossier.character_name.strip()
            items.append(
                {
                    "source": "Dossier",
                    "question_id": "Name",
                    "label": "Character Name differs",
                    "detail": f"Dossier '{target_dossier.character_name}' vs Sheet '{character.character_name}'",
                }
            )
        d_resp = target_dossier.responses if isinstance(target_dossier.responses, dict) else {}
        for qid, topic in SHEET_TRACKED_DOSSIER_IDS.items():
            rec = d_resp.get(qid)
            if not isinstance(rec, dict) or not str(rec.get("answer", "")).strip():
                continue
            rec_dt = _parse_iso_dt(rec.get("updated_at"))
            if rec_dt is not None and (baseline_dt is None or rec_dt > baseline_dt):
                snippet = str(rec.get("answer", "")).strip().splitlines()[0][:120]
                items.append(
                    {
                        "source": "Dossier",
                        "question_id": f"[{qid}]",
                        "label": topic,
                        "detail": snippet,
                    }
                )

    for c in censuses:
        if (
            c.character_name
            and c.character_name.strip() != character.character_name.strip()
            and (baseline_dt is None or c.updated_at > baseline_dt)
        ):
            if not suggested_name:
                suggested_name = c.character_name.strip()
            items.append(
                {
                    "source": "Census",
                    "question_id": "Name",
                    "label": "Character Name differs",
                    "detail": f"Census '{c.character_name}' vs Sheet '{character.character_name}'",
                }
            )
        c_resp = c.responses if isinstance(c.responses, dict) else {}
        for qid, topic in SHEET_TRACKED_CENSUS_IDS.items():
            rec = c_resp.get(qid)
            if not isinstance(rec, dict) or not str(rec.get("answer", "")).strip():
                continue
            rec_dt = _parse_iso_dt(rec.get("updated_at"))
            if rec_dt is not None and (baseline_dt is None or rec_dt > baseline_dt):
                snippet = str(rec.get("answer", "")).strip().splitlines()[0][:120]
                items.append(
                    {
                        "source": "Census",
                        "question_id": f"[{qid}]",
                        "label": topic,
                        "detail": snippet,
                    }
                )

    return {
        "has_pending": bool(items),
        "count": len(items),
        "items": items[:12],
        "suggested_name": suggested_name,
    }
