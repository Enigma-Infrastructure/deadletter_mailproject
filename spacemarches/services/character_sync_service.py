"""Cloud persistence, summary extraction, Dossier linking, and sheet export for generated EP2E characters."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import slugify

from spacemarches.models import CharacterDossier, EclipsePhaseCensus, Ep2Entry, GeneratedCharacter

MESHNET_DESIGNS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "meshnet-pack-designs.json"


@lru_cache(maxsize=1)
def _load_meshnet_design_lookup() -> dict[str, dict[str, Any]]:
    """Index MeshNet pack design rows by key and uid for label/skillPack resolution."""
    lookup: dict[str, dict[str, Any]] = {}
    if not MESHNET_DESIGNS_PATH.exists():
        return lookup
    try:
        rows = json.loads(MESHNET_DESIGNS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return lookup
    if not isinstance(rows, list):
        return lookup
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        lookup[key] = row
    return lookup


def _lookup_design_name_by_key(design_key: str) -> str:
    if not design_key:
        return ""
    row = _load_meshnet_design_lookup().get(design_key)
    if row and row.get("name"):
        return _unwrap_tagged_text(row.get("name"))
    entry = Ep2Entry.objects.filter(entry_id__endswith=f":{design_key}").only("name").first()
    if entry and entry.name:
        return entry.name
    return ""


def get_sheet_skill_pack_choices() -> dict[str, list[dict[str, str]]]:
    """Return official EP2e skillPack options grouped by background/career/interest/faction."""
    grouped: dict[str, list[dict[str, str]]] = {
        "background": [],
        "career": [],
        "interest": [],
        "faction": [],
    }
    seen: dict[str, set[str]] = {k: set() for k in grouped}

    # Prefer seeded Ep2Entry rows if available
    db_rows = Ep2Entry.objects.filter(category=Ep2Entry.CATEGORY_SKILL_PACK).select_related("design_pack")
    for entry in db_rows:
        sys_data = entry.system if isinstance(entry.system, dict) else {}
        slot = str(sys_data.get("skillPackType") or "").strip().lower()
        eid = str(entry.entry_id or "").strip()
        key = eid.rsplit(":", 1)[-1].strip() if ":" in eid else eid
        pack_slug = entry.design_pack.slug if entry.design_pack_id and entry.design_pack else (entry.pack or "ep-crb")
        if slot in grouped and key and entry.name not in seen[slot]:
            seen[slot].add(entry.name)
            grouped[slot].append(
                {
                    "key": key,
                    "name": entry.name,
                    "pack": pack_slug,
                    "uid": f"skillPack:{pack_slug}:{key}",
                }
            )

    # Supplement / fallback from meshnet-pack-designs.json so unseeded or test DBs work cleanly
    for row in _load_meshnet_design_lookup().values():
        if row.get("design_type") != "skillPack":
            continue
        sys_data = row.get("system") if isinstance(row.get("system"), dict) else {}
        slot = str(sys_data.get("skillPackType") or "").strip().lower()
        key = str(row.get("key") or "").strip()
        name = _unwrap_tagged_text(row.get("name"))
        pack_slug = str(row.get("pack") or "ep-crb").strip()
        if slot in grouped and key and name and name not in seen[slot]:
            seen[slot].add(name)
            grouped[slot].append(
                {
                    "key": key,
                    "name": name,
                    "pack": pack_slug,
                    "uid": f"skillPack:{pack_slug}:{key}",
                }
            )

    for slot in grouped:
        grouped[slot].sort(key=lambda item: item["name"].lower())
    return grouped

EP2_ENTRIES_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "ep2_entries.json"

APTITUDE_TEMPLATES: list[dict[str, Any]] = [
    {"key": "actioneer", "name": "Actioneer", "aptitudes": {"cog": 10, "int": 15, "ref": 20, "sav": 10, "som": 20, "wil": 15}},
    {"key": "extrovert", "name": "Extrovert", "aptitudes": {"cog": 10, "int": 20, "ref": 15, "sav": 20, "som": 15, "wil": 10}},
    {"key": "facilitator", "name": "Facilitator", "aptitudes": {"cog": 15, "int": 15, "ref": 10, "sav": 20, "som": 10, "wil": 20}},
    {"key": "factotum", "name": "Factotum", "aptitudes": {"cog": 15, "int": 15, "ref": 15, "sav": 15, "som": 15, "wil": 15}},
    {"key": "inquirer", "name": "Inquirer", "aptitudes": {"cog": 20, "int": 20, "ref": 10, "sav": 15, "som": 10, "wil": 15}},
    {"key": "survivor", "name": "Survivor", "aptitudes": {"cog": 15, "int": 10, "ref": 15, "sav": 10, "som": 20, "wil": 20}},
    {"key": "thrillSeeker", "name": "Thrill Seeker", "aptitudes": {"cog": 20, "int": 10, "ref": 20, "sav": 15, "som": 15, "wil": 10}},
]


@lru_cache(maxsize=1)
def _load_bubz_ep2_fixture() -> list[dict[str, Any]]:
    if not EP2_ENTRIES_PATH.exists():
        return []
    try:
        rows = json.loads(EP2_ENTRIES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def get_sheet_rep_choices() -> list[dict[str, str]]:
    """Return official EP2e reputation networks from Ep2Entry or meshnet-pack-designs fallback."""
    reps: list[dict[str, str]] = []
    seen: set[str] = set()
    db_rows = Ep2Entry.objects.filter(category=Ep2Entry.CATEGORY_REP, is_storyteller_only=False).select_related("design_pack")
    for entry in db_rows:
        eid = str(entry.entry_id or "").strip()
        key = eid.rsplit(":", 1)[-1].strip() if ":" in eid else eid
        pack_slug = entry.design_pack.slug if entry.design_pack_id and entry.design_pack else (entry.pack or "ep-crb")
        if key and entry.name and entry.name not in seen:
            seen.add(entry.name)
            reps.append({"key": key, "name": entry.name, "pack": pack_slug, "uid": f"rep:{pack_slug}:{key}"})

    for row in _load_meshnet_design_lookup().values():
        if row.get("design_type") != "rep":
            continue
        key = str(row.get("key") or "").strip()
        name = _unwrap_tagged_text(row.get("name"))
        pack_slug = str(row.get("pack") or "ep-crb").strip()
        if key and name and name not in seen:
            seen.add(name)
            reps.append({"key": key, "name": name, "pack": pack_slug, "uid": f"rep:{pack_slug}:{key}"})

    reps.sort(key=lambda item: item["name"].lower())
    return reps


def get_sheet_morph_choices() -> list[dict[str, str]]:
    """Return available morph options from Ep2Entry (Bubz/MeshNet) with fixture fallback."""
    from spacemarches.services.meshnet_adapter_service import _convert_entry, _SAFE_KEY_RE

    morphs: list[dict[str, str]] = []
    seen_names: set[str] = set()
    db_rows = (
        Ep2Entry.objects.filter(category=Ep2Entry.CATEGORY_MORPH, is_storyteller_only=False)
        .select_related("design_pack")
        .order_by("name")
    )
    for entry in db_rows:
        pack_slug = entry.design_pack.slug if entry.design_pack_id and entry.design_pack else (entry.pack or "bubz-ep2e")
        pack_name = entry.design_pack.name if entry.design_pack_id and entry.design_pack else "EP2e Compendium"
        converted = _convert_entry(entry, pack_name=pack_name)
        if not converted:
            continue
        design_type, _design = converted
        if (entry.source or "").strip().lower() == "meshnet" and ":" in (entry.entry_id or ""):
            key = entry.entry_id.split(":", 2)[2]
        else:
            key = _SAFE_KEY_RE.sub("-", (entry.entry_id or slugify(entry.name) or f"entry-{entry.pk}").strip()).strip("-")[:48]
        uid = f"{design_type}:{pack_slug}:{key}"
        if entry.name and entry.name not in seen_names:
            seen_names.add(entry.name)
            morphs.append(
                {
                    "key": key,
                    "name": entry.name,
                    "design_type": design_type,
                    "pack": pack_slug,
                    "uid": uid,
                    "entry_id": entry.entry_id,
                }
            )

    if not morphs:
        for row in _load_bubz_ep2_fixture():
            fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
            if fields.get("category") != Ep2Entry.CATEGORY_MORPH or fields.get("is_storyteller_only"):
                continue
            name = str(fields.get("name") or "").strip()
            etype = str(fields.get("entry_type") or "").strip().lower()
            sys_data = fields.get("system") if isinstance(fields.get("system"), dict) else {}
            if etype == "biological":
                dtype = "biologicalBody"
            elif etype == "infomorph":
                dtype = "digitalForm"
            elif sys_data.get("isSwarm"):
                dtype = "swarm"
            else:
                dtype = "syntheticShell"
            eid = str(fields.get("entry_id") or slugify(name)).strip()
            key = _SAFE_KEY_RE.sub("-", eid).strip("-")[:48]
            pack_slug = str(fields.get("pack") or "bubz-ep2e").strip()
            uid = f"{dtype}:{pack_slug}:{key}"
            if name and name not in seen_names:
                seen_names.add(name)
                morphs.append(
                    {
                        "key": key,
                        "name": name,
                        "design_type": dtype,
                        "pack": pack_slug,
                        "uid": uid,
                        "entry_id": eid,
                    }
                )

    morphs.sort(key=lambda item: item["name"].lower())
    return morphs


MAX_RAW_CHARACTER_BYTES = 2_000_000


def _unwrap_tagged_text(value: Any, default: str = "") -> str:
    """Resolve MeshNet TaggedString ({custom, msgId, ...} / string) into readable text."""
    if value is None:
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.startswith(("i_", "m_", "h_")):
            cleaned = cleaned[2:].strip()
        return cleaned or default
    if isinstance(value, dict):
        for key in ("custom", "text", "value", "name", "en", "en-US"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        msg_id = value.get("msgId")
        if isinstance(msg_id, str) and msg_id.strip():
            return msg_id.strip()
    return default


def _format_uid_label(uid: Any) -> str:
    """Turn a DesignUid like 'skill-pack:academic' or object into a human-friendly label."""
    if not isinstance(uid, str):
        return _unwrap_tagged_text(uid)
    raw = uid.strip()
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw.replace("-", " ").replace("_", " ").strip().title()


def _extract_design_label(entry: Any, packs: dict[str, Any]) -> str:
    """Extract a readable label from a MeshNet design instance or design ref."""
    if not isinstance(entry, dict):
        return _unwrap_tagged_text(entry)
    direct = _unwrap_tagged_text(entry.get("customName")) or _unwrap_tagged_text(entry.get("name"))
    design = entry.get("design") if isinstance(entry.get("design"), dict) else entry
    custom = design.get("custom") if isinstance(design, dict) else None
    if isinstance(custom, dict):
        name = _unwrap_tagged_text(custom.get("name"))
        if name:
            return direct or name
    uid = (design.get("uid") or design.get("id")) if isinstance(design, dict) else (entry.get("uid") or entry.get("id"))
    if isinstance(uid, str) and uid:
        uid_parts = uid.split(":", 2)
        design_type = uid_parts[0] if len(uid_parts) == 3 else ""
        design_key = uid_parts[2] if len(uid_parts) == 3 else ""
        # Attempt lookup inside bundled partial packs if exported
        for pack in packs.values():
            if not isinstance(pack, dict):
                continue
            collections = (
                pack.get("designs")
                if isinstance(pack.get("designs"), dict)
                else (pack.get("collections") if isinstance(pack.get("collections"), dict) else pack)
            )
            if not isinstance(collections, dict):
                continue
            if design_type and design_key and isinstance(collections.get(design_type), dict):
                typed_col = collections[design_type]
                if isinstance(typed_col.get(design_key), dict):
                    raw_name = typed_col[design_key].get("name")
                    if isinstance(raw_name, str) and raw_name.startswith("m_"):
                        resolved = _lookup_design_name_by_key(design_key)
                        if resolved:
                            return direct or resolved
                    label = _unwrap_tagged_text(raw_name)
                    if label:
                        return direct or label
            for col in collections.values():
                if not isinstance(col, dict):
                    continue
                for candidate_key in (uid, design_key):
                    if candidate_key and isinstance(col.get(candidate_key), dict):
                        raw_name = col[candidate_key].get("name")
                        if isinstance(raw_name, str) and raw_name.startswith("m_"):
                            resolved = _lookup_design_name_by_key(design_key)
                            if resolved:
                                return direct or resolved
                        label = _unwrap_tagged_text(raw_name)
                        if label:
                            return direct or label
        key_name = _lookup_design_name_by_key(design_key)
        if key_name:
            return direct or key_name
        return direct or _format_uid_label(uid)
    return direct


def extract_point_buy_summary(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Build a safe, lightweight display summary from a MeshNet Point-Buy v2 JSON payload."""
    if not isinstance(raw_data, dict):
        return {}

    pb = raw_data.get("pointBuy") if isinstance(raw_data.get("pointBuy"), dict) else raw_data
    if not isinstance(pb, dict):
        return {}
    packs = raw_data.get("packs") if isinstance(raw_data.get("packs"), dict) else {}

    character_name = _unwrap_tagged_text(pb.get("name"), default="Unnamed Agent")
    full_name = _unwrap_tagged_text(pb.get("fullName"))
    concept = _unwrap_tagged_text(pb.get("concept"))
    ego_type = _unwrap_tagged_text(pb.get("egoType"))
    gender = _unwrap_tagged_text(pb.get("gender"))
    description = _unwrap_tagged_text(pb.get("description"))
    muse_name = _unwrap_tagged_text(pb.get("museName"))

    aptitudes: dict[str, int] = {}
    raw_apts = pb.get("aptitudes")
    if isinstance(raw_apts, dict):
        for k, v in raw_apts.items():
            if isinstance(v, (int, float)):
                aptitudes[str(k).lower()] = int(v)

    skill_packs: dict[str, str] = {}
    raw_packs = pb.get("skillPacks")
    if isinstance(raw_packs, dict):
        for slot_key in ("background", "career", "interest", "faction"):
            label = _extract_design_label(raw_packs.get(slot_key), packs)
            if label:
                skill_packs[slot_key] = label

    morphs: list[str] = []
    raw_morphs = pb.get("morphs")
    if isinstance(raw_morphs, dict):
        for entry in raw_morphs.values():
            label = _extract_design_label(entry, packs)
            if label:
                morphs.append(label)

    traits: list[str] = []
    raw_traits = pb.get("egoTraits")
    if isinstance(raw_traits, dict):
        for entry in raw_traits.values():
            label = _extract_design_label(entry, packs)
            if label:
                traits.append(label)

    sleights: list[str] = []
    raw_sleights = pb.get("sleights")
    if isinstance(raw_sleights, dict):
        for entry in raw_sleights.values():
            label = _extract_design_label(entry, packs)
            if label:
                sleights.append(label)

    reputations: dict[str, int] = {}
    raw_reps = pb.get("reputations")
    if isinstance(raw_reps, dict):
        for entry in raw_reps.values():
            if isinstance(entry, dict):
                rep_label = _extract_design_label(entry, packs) or "Rep"
                pts = entry.get("score") if entry.get("score") is not None else entry.get("points")
                if isinstance(pts, (int, float)):
                    reputations[rep_label] = int(pts)

    languages: list[str] = []
    raw_langs = pb.get("languages")
    if isinstance(raw_langs, list):
        for lang in raw_langs:
            text = _unwrap_tagged_text(lang)
            if text:
                languages.append(text)

    motivations: list[str] = []
    raw_mots = pb.get("motivations")
    if isinstance(raw_mots, dict):
        for mot in raw_mots.values():
            if isinstance(mot, dict):
                goal = (
                    _unwrap_tagged_text(mot.get("cause"))
                    or _unwrap_tagged_text(mot.get("goal"))
                    or _unwrap_tagged_text(mot.get("description"))
                )
                stance = str(mot.get("stance") or "").strip()
                if not stance and "supportCause" in mot:
                    stance = "+ Support" if mot.get("supportCause") else "- Oppose"
                if goal:
                    motivations.append(f"{stance}: {goal}" if stance else goal)

    raw_skills = pb.get("skills")
    skill_count = len(raw_skills) if isinstance(raw_skills, dict) else 0
    flex_points = pb.get("flexPoints")
    flex = int(flex_points) if isinstance(flex_points, (int, float)) else 0

    return {
        "character_name": character_name[:160],
        "full_name": full_name[:160],
        "concept": concept[:240],
        "ego_type": ego_type[:80],
        "gender": gender[:80],
        "description": description[:600],
        "muse_name": muse_name[:120],
        "aptitudes": aptitudes,
        "flex": flex,
        "skill_packs": skill_packs,
        "morphs": morphs[:10],
        "traits": traits[:20],
        "sleights": sleights[:20],
        "reputations": reputations,
        "languages": languages[:15],
        "motivations": motivations[:10],
        "skill_count": skill_count,
    }


def _resolve_accessible_dossier_for_user(user, dossier_id: int | str) -> CharacterDossier:
    try:
        pk = int(dossier_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid dossier_id.") from exc

    qs = CharacterDossier.objects.all()
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        dossier = qs.filter(pk=pk).first()
    else:
        dossier = qs.filter(pk=pk, user=user).first()
    if dossier is None:
        raise ValueError("Selected character dossier was not found or is not accessible.")
    return dossier


def save_generated_character(
    user,
    *,
    external_id: str = "",
    character_name: str = "",
    source_system: str = GeneratedCharacter.SOURCE_POINT_BUY_V2,
    raw_data: dict[str, Any] | None = None,
    dossier_id: int | str | None = None,
    character_pk: int | None = None,
) -> tuple[GeneratedCharacter, bool]:
    """Create or update a GeneratedCharacter owned by the authenticated user."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required to save a generated character.")

    payload = {} if raw_data is None else raw_data
    if not isinstance(payload, dict):
        raise ValueError("raw_data must be a JSON object.")

    encoded = json.dumps(payload, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_RAW_CHARACTER_BYTES:
        raise ValueError("Character payload exceeds maximum allowed size (2 MB).")

    valid_sources = {choice[0] for choice in GeneratedCharacter.SOURCE_SYSTEM_CHOICES}
    norm_source = str(source_system or GeneratedCharacter.SOURCE_POINT_BUY_V2).strip()
    if norm_source not in valid_sources:
        norm_source = GeneratedCharacter.SOURCE_POINT_BUY_V2

    if norm_source == GeneratedCharacter.SOURCE_POINT_BUY_V2:
        payload = ensure_valid_point_buy_payload(payload, character_name=character_name)
    summary = extract_point_buy_summary(payload)
    resolved_name = (character_name or "").strip() or summary.get("character_name") or "Unnamed Agent"
    resolved_name = resolved_name[:160]
    summary["character_name"] = resolved_name

    norm_ext_id = str(external_id or "").strip()[:64]

    dossier_obj: CharacterDossier | None = None
    has_dossier_arg = dossier_id is not None and str(dossier_id).strip() != ""
    if has_dossier_arg:
        dossier_obj = _resolve_accessible_dossier_for_user(user, dossier_id)

    with transaction.atomic():
        existing: GeneratedCharacter | None = None
        if character_pk is not None:
            existing = GeneratedCharacter.objects.filter(pk=character_pk, user=user).first()
        if existing is None and norm_ext_id:
            existing = GeneratedCharacter.objects.filter(user=user, external_id=norm_ext_id).first()

        if existing is not None:
            if norm_source == GeneratedCharacter.SOURCE_POINT_BUY_V2 and isinstance(existing.raw_data, dict):
                prev_packs = existing.raw_data.get("packs")
                inc_packs = payload.get("packs") if isinstance(payload.get("packs"), dict) else {}
                if isinstance(prev_packs, dict) and prev_packs:
                    payload["packs"] = {**prev_packs, **inc_packs}
                    summary = extract_point_buy_summary(payload)
                    summary["character_name"] = resolved_name
            existing.character_name = resolved_name
            existing.source_system = norm_source
            existing.raw_data = payload
            existing.summary = summary
            if norm_ext_id:
                existing.external_id = norm_ext_id
            if dossier_id is not None:
                existing.dossier = dossier_obj
            existing.save()
            return existing, False

        created_obj = GeneratedCharacter.objects.create(
            user=user,
            dossier=dossier_obj,
            external_id=norm_ext_id,
            character_name=resolved_name,
            source_system=norm_source,
            raw_data=payload,
            summary=summary,
            # A saved sheet is finalized: Finalize pushes it to be completed.
            # A sheet that is later re-saved stays at its current status.
            status=GeneratedCharacter.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        return created_obj, True


def link_character_to_dossier(
    user,
    character: GeneratedCharacter,
    *,
    dossier_id: int | str | None = None,
    create_dossier: bool = False,
    narrative_voice: str = CharacterDossier.VOICE_FIRST_PERSON,
) -> CharacterDossier | None:
    """Attach, unlink, or create-and-link a CharacterDossier for a GeneratedCharacter."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required.")
    if character.user_id != user.pk and not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        raise ValueError("You do not have permission to update this character.")

    if create_dossier:
        voice = narrative_voice if narrative_voice in {
            CharacterDossier.VOICE_FIRST_PERSON,
            CharacterDossier.VOICE_OMNISCIENT,
        } else CharacterDossier.VOICE_FIRST_PERSON

        base_slug = slugify(character.character_name)[:140] or "character"
        slug = base_slug
        counter = 1
        while CharacterDossier.objects.filter(user=character.user, slug=slug).exists():
            counter += 1
            slug = f"{base_slug[:140]}-{counter}"

        dossier = CharacterDossier.objects.create(
            user=character.user,
            character_name=character.character_name[:160],
            slug=slug,
            narrative_voice=voice,
        )
        character.dossier = dossier
        character.save(update_fields=["dossier", "updated_at"])
        return dossier

    if dossier_id is None or str(dossier_id).strip() == "":
        character.dossier = None
        character.save(update_fields=["dossier", "updated_at"])
        return None

    dossier = _resolve_accessible_dossier_for_user(user, dossier_id)
    character.dossier = dossier
    character.save(update_fields=["dossier", "updated_at"])
    return dossier


def serialize_generated_character(character: GeneratedCharacter, *, include_raw: bool = False) -> dict[str, Any]:
    """Serialize a GeneratedCharacter into a safe JSON dict for the frontend generator & roster."""
    dossier_data = None
    dossier_id = None
    dossier_slug = ""
    dossier_name = ""
    dossier_url = ""
    if character.dossier_id and character.dossier is not None:
        dossier_id = character.dossier_id
        dossier_slug = character.dossier.slug
        dossier_name = character.dossier.character_name
        dossier_url = reverse("spacemarches:dossier_detail", kwargs={"slug": dossier_slug})
        dossier_data = {
            "id": dossier_id,
            "character_name": dossier_name,
            "slug": dossier_slug,
            "url": dossier_url,
        }

    data: dict[str, Any] = {
        "id": character.pk,
        "external_id": character.external_id,
        "character_name": character.character_name,
        "source_system": character.source_system,
        "summary": character.summary if isinstance(character.summary, dict) else {},
        "dossier": dossier_data,
        "dossier_id": dossier_id,
        "dossier_slug": dossier_slug,
        "dossier_name": dossier_name,
        "dossier_url": dossier_url,
        "created_at": character.created_at.isoformat(),
        "updated_at": character.updated_at.isoformat(),
        "export_html_url": reverse("spacemarches:character_export", kwargs={"pk": character.pk}) + "?format=html",
        "export_json_url": reverse("spacemarches:character_export", kwargs={"pk": character.pk}) + "?format=json",
        "export_md_url": reverse("spacemarches:character_export", kwargs={"pk": character.pk}) + "?format=md",
    }
    if include_raw:
        raw_val = character.raw_data if isinstance(character.raw_data, dict) else {}
        if character.source_system == GeneratedCharacter.SOURCE_POINT_BUY_V2:
            raw_val = ensure_valid_point_buy_payload(raw_val, character_name=character.character_name)
        data["raw_data"] = raw_val
    return data


def export_generated_character_markdown(character: GeneratedCharacter) -> str:
    """Render a generated EP2E character sheet into clean portable Markdown."""
    summary = character.summary if isinstance(character.summary, dict) else extract_point_buy_summary(character.raw_data)
    lines: list[str] = [
        f"# {character.character_name}",
        "",
        f"- **System:** {character.get_source_system_display()}",
    ]
    if summary.get("full_name"):
        lines.append(f"- **Full Name:** {summary['full_name']}")
    if summary.get("concept"):
        lines.append(f"- **Concept:** {summary['concept']}")
    if summary.get("ego_type"):
        lines.append(f"- **Ego Type:** {summary['ego_type']}")
    if summary.get("gender"):
        lines.append(f"- **Gender:** {summary['gender']}")
    if summary.get("muse_name"):
        lines.append(f"- **Muse:** {summary['muse_name']}")
    if character.dossier_id and character.dossier is not None:
        lines.append(f"- **Linked Narrative Dossier:** {character.dossier.character_name} (`{character.dossier.slug}`)")

    skill_packs = summary.get("skill_packs") or {}
    if skill_packs:
        lines.extend(["", "## Lifepath Packs"])
        for k in ("background", "career", "interest", "faction"):
            if skill_packs.get(k):
                lines.append(f"- **{k.title()}:** {skill_packs[k]}")

    apts = summary.get("aptitudes") or {}
    if apts:
        lines.extend(["", "## Aptitudes", "", "| COG | INT | REF | SAV | SOM | WIL | Flex |", "| --- | --- | --- | --- | --- | --- | --- |"])
        row = " | ".join(str(apts.get(k, "—")) for k in ("cog", "int", "ref", "sav", "som", "wil"))
        lines.append(f"| {row} | {summary.get('flex', 0)} |")

    morphs = summary.get("morphs") or []
    if morphs:
        lines.extend(["", "## Morphs", *[f"- {m}" for m in morphs]])

    reps = summary.get("reputations") or {}
    if reps:
        lines.extend(["", "## Reputations", *[f"- **{k}:** {v}" for k, v in reps.items()]])

    traits = summary.get("traits") or []
    if traits:
        lines.extend(["", "## Ego Traits", *[f"- {t}" for t in traits]])

    sleights = summary.get("sleights") or []
    if sleights:
        lines.extend(["", "## Psi Sleights", *[f"- {s}" for s in sleights]])

    languages = summary.get("languages") or []
    if languages:
        lines.extend(["", "## Languages", *[f"- {lang}" for lang in languages]])

    motivations = summary.get("motivations") or []
    if motivations:
        lines.extend(["", "## Motivations", *[f"- {mot}" for mot in motivations]])

    if summary.get("description"):
        lines.extend(["", "## Notes & Description", "", summary["description"]])

    lines.append("")
    return "\n".join(lines)


def export_generated_character_html(character: GeneratedCharacter) -> str:
    """Render a standalone printable HTML character sheet for a GeneratedCharacter."""
    summary = character.summary if isinstance(character.summary, dict) else extract_point_buy_summary(character.raw_data)
    name = escape(character.character_name)
    concept = escape(summary.get("concept") or "")
    ego_type = escape(summary.get("ego_type") or "")
    full_name = escape(summary.get("full_name") or "")
    muse_name = escape(summary.get("muse_name") or "")
    apts = summary.get("aptitudes") or {}
    skill_packs = summary.get("skill_packs") or {}
    morphs = summary.get("morphs") or []
    traits = summary.get("traits") or []
    sleights = summary.get("sleights") or []
    reps = summary.get("reputations") or {}
    languages = summary.get("languages") or []
    motivations = summary.get("motivations") or []

    apt_cells = "".join(
        f"<td><strong>{k.upper()}</strong><span>{escape(str(apts.get(k, '—')))}</span></td>"
        for k in ("cog", "int", "ref", "sav", "som", "wil")
    )
    apt_cells += f"<td><strong>FLEX</strong><span>{escape(str(summary.get('flex', 0)))}</span></td>"

    def _list_block(title: str, items: list[str]) -> str:
        if not items:
            return ""
        lis = "".join(f"<li>{escape(str(item))}</li>" for item in items)
        return f"<section><h2>{escape(title)}</h2><ul>{lis}</ul></section>"

    packs_items = [f"{k.title()}: {v}" for k, v in skill_packs.items() if v]
    reps_items = [f"{k}: {v}" for k, v in reps.items()]
    notes_html = f"<section><h2>Description</h2><p>{escape(summary.get('description') or '')}</p></section>" if summary.get("description") else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{name} — Eclipse Phase 2E Character Sheet</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{ color-scheme: light dark; --bg: #f8fafc; --card: #ffffff; --fg: #0f172a; --muted: #475569; --border: #cbd5e1; --accent: #0f766e; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --bg: #0b111a; --card: #111927; --fg: #e2e8f0; --muted: #94a3b8; --border: #263244; --accent: #38bdf8; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 2rem 1rem; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); line-height: 1.5; }}
    main {{ max-width: 820px; margin: 0 auto; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 2rem; }}
    h1 {{ margin: 0 0 0.25rem; font-size: 1.75rem; }}
    h2 {{ margin: 1.5rem 0 0.5rem; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 0.25rem; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 1rem; }}
    table.apts {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-variant-numeric: tabular-nums; }}
    table.apts td {{ border: 1px solid var(--border); padding: 0.5rem; text-align: center; }}
    table.apts strong {{ display: block; font-size: 0.72rem; color: var(--muted); }}
    table.apts span {{ font-size: 1.25rem; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }}
    ul {{ margin: 0.25rem 0; padding-left: 1.2rem; }}
    @media print {{ body {{ background: #fff; padding: 0; }} main {{ border: none; padding: 0; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{name}</h1>
      <div class="meta">
        {f"Full Name: {full_name} &middot; " if full_name else ""}
        {f"Concept: {concept} &middot; " if concept else ""}
        {f"Ego: {ego_type} &middot; " if ego_type else ""}
        {f"Muse: {muse_name} &middot; " if muse_name else ""}
        System: {escape(character.get_source_system_display())}
      </div>
    </header>
    <table class="apts"><tbody><tr>{apt_cells}</tr></tbody></table>
    <div class="grid">
      {_list_block("Background & Faction", packs_items)}
      {_list_block("Morphs", morphs)}
      {_list_block("Reputations", reps_items)}
      {_list_block("Ego Traits", traits)}
      {_list_block("Psi Sleights", sleights)}
      {_list_block("Languages", languages)}
      {_list_block("Motivations", motivations)}
    </div>
    {notes_html}
  </main>
</body>
</html>
"""



def _encode_tagged_input(value: str) -> str:
    cleaned = (value or "").strip()
    return f"i_{cleaned}" if cleaned else "i_"


def _find_skill_pack_option(slot: str, selection: str) -> dict[str, str] | None:
    needle = (selection or "").strip()
    if not needle:
        return None
    options = get_sheet_skill_pack_choices().get(slot, [])
    needle_cf = needle.casefold()
    for opt in options:
        if opt["key"] == needle or opt["uid"] == needle or opt["name"].casefold() == needle_cf:
            return opt
    return None


def _find_rep_option(selection: str) -> dict[str, str] | None:
    needle = (selection or "").strip()
    if not needle:
        return None
    needle_cf = needle.casefold()
    for opt in get_sheet_rep_choices():
        if opt["key"].casefold() == needle_cf or opt["uid"].casefold() == needle_cf or opt["name"].casefold() == needle_cf:
            return opt
    return None


def _find_morph_option(selection: str) -> dict[str, str] | None:
    needle = (selection or "").strip()
    if not needle:
        return None
    needle_cf = needle.casefold()
    for opt in get_sheet_morph_choices():
        if opt["uid"].casefold() == needle_cf or opt["key"].casefold() == needle_cf or opt["name"].casefold() == needle_cf:
            return opt
    return None


def ensure_valid_point_buy_payload(
    raw_data: dict[str, Any] | None,
    *,
    character_name: str = "",
) -> dict[str, Any]:
    """Normalize a partial or bare PointBuy dict into valid PointBuyExported JSON for MeshNet."""
    data = copy.deepcopy(raw_data) if isinstance(raw_data, dict) else {}
    if isinstance(data.get("pointBuy"), dict):
        pb = data["pointBuy"]
    else:
        pb = dict(data)
        data = {}

    apts = pb.get("aptitudes") if isinstance(pb.get("aptitudes"), dict) else {}
    norm_apts: dict[str, int] = {}
    for k in ("cog", "int", "ref", "sav", "som", "wil"):
        raw_v = apts.get(k, 15)
        try:
            val = int(raw_v)
        except (TypeError, ValueError):
            val = 15
        norm_apts[k] = max(0, min(30, val))

    resolved_name = _unwrap_tagged_text(pb.get("name")) or (character_name or "").strip() or "Unnamed Agent"
    flex_raw = pb.get("flexPoints", 1)
    try:
        flex_val = max(0, min(3, int(flex_raw)))
    except (TypeError, ValueError):
        flex_val = 1

    norm_pb: dict[str, Any] = {
        **pb,
        "aptitudes": norm_apts,
        "concept": pb.get("concept") if isinstance(pb.get("concept"), str) else _encode_tagged_input(_unwrap_tagged_text(pb.get("concept"))),
        "config": pb.get("config") if isinstance(pb.get("config"), dict) else {},
        "currentStep": str(pb.get("currentStep") or "background"),
        "description": pb.get("description") if isinstance(pb.get("description"), str) else "h_",
        "egoTraits": pb.get("egoTraits") if isinstance(pb.get("egoTraits"), dict) else {},
        "egoType": pb.get("egoType") if isinstance(pb.get("egoType"), str) else "i_Transhuman",
        "expertTraining": pb.get("expertTraining") if isinstance(pb.get("expertTraining"), dict) else {},
        "flexPoints": flex_val,
        "fullName": pb.get("fullName") if isinstance(pb.get("fullName"), str) else "i_",
        "gear": pb.get("gear") if isinstance(pb.get("gear"), dict) else {},
        "gender": pb.get("gender") if isinstance(pb.get("gender"), str) else "i_",
        "languages": pb.get("languages") if isinstance(pb.get("languages"), list) else [],
        "morphs": pb.get("morphs") if isinstance(pb.get("morphs"), dict) else {},
        "motivations": pb.get("motivations") if isinstance(pb.get("motivations"), dict) else {},
        "museName": pb.get("museName") if isinstance(pb.get("museName"), str) else "i_",
        "name": pb.get("name") if (isinstance(pb.get("name"), str) and pb["name"] != "i_") else _encode_tagged_input(resolved_name),
        "reputations": pb.get("reputations") if isinstance(pb.get("reputations"), dict) else {},
        "skillPacks": pb.get("skillPacks") if isinstance(pb.get("skillPacks"), dict) else {},
        "skills": pb.get("skills") if isinstance(pb.get("skills"), dict) else {},
        "sleights": pb.get("sleights") if isinstance(pb.get("sleights"), dict) else {},
        "substrains": pb.get("substrains") if isinstance(pb.get("substrains"), dict) else {},
    }

    out = {
        **{k: v for k, v in data.items() if k != "pointBuy"},
        "type": "point-buy-exported",
        "createdAt": str(data.get("createdAt") or timezone.now().isoformat()),
        "packs": data.get("packs") if isinstance(data.get("packs"), dict) else {},
        "pointBuy": norm_pb,
    }
    return out


def _embed_morph_pack_design(raw_data: dict[str, Any], opt: dict[str, str]) -> None:
    """Ensure raw_data['packs'] embeds external morph design definitions (e.g., bubz-ep2e)."""
    from spacemarches.services.meshnet_adapter_service import _convert_entry

    entry_id = str(opt.get("entry_id") or "").strip()
    pack_name = "EP2e Compendium"
    design_type = opt.get("design_type") or "biologicalBody"
    design_dict: dict[str, Any] | None = None

    if entry_id:
        entry = Ep2Entry.objects.filter(entry_id=entry_id).select_related("design_pack").first()
        if entry is None:
            for row in _load_bubz_ep2_fixture():
                fields = row.get("fields") if isinstance(row, dict) and isinstance(row.get("fields"), dict) else {}
                if str(fields.get("entry_id") or "").strip() == entry_id:
                    entry = Ep2Entry(
                        entry_id=entry_id,
                        source=str(fields.get("source") or "bubz-ep2e"),
                        name=str(fields.get("name") or opt.get("name") or ""),
                        category=str(fields.get("category") or Ep2Entry.CATEGORY_MORPH),
                        entry_type=str(fields.get("entry_type") or ""),
                        pack=str(fields.get("pack") or opt.get("pack") or "bubz-ep2e"),
                        description=str(fields.get("description") or ""),
                        reference=str(fields.get("reference") or ""),
                        system=fields.get("system") if isinstance(fields.get("system"), dict) else {},
                    )
                    break
        else:
            if entry.design_pack_id and entry.design_pack:
                pack_name = entry.design_pack.name
        if entry is not None:
            converted = _convert_entry(entry, pack_name=pack_name)
            if converted:
                design_type, design_dict = converted

    if design_dict is None:
        design_dict = {
            "name": _encode_tagged_input(opt.get("name") or opt.get("key") or "Morph"),
            "type": design_type,
        }

    raw_packs = raw_data.setdefault("packs", {})
    pack_bucket = raw_packs.setdefault(
        opt["pack"],
        {"name": _encode_tagged_input(pack_name), "designs": {}},
    )
    designs_bucket = pack_bucket.setdefault("designs", {})
    typed_bucket = designs_bucket.setdefault(design_type, {})
    typed_bucket[opt["key"]] = design_dict


def update_sheet_profile_fields(
    user,
    character: GeneratedCharacter,
    *,
    character_name: str | None = None,
    full_name: str | None = None,
    concept: str | None = None,
    ego_type: str | None = None,
    gender: str | None = None,
    muse_name: str | None = None,
    description: str | None = None,
    languages: list[str] | str | None = None,
    skill_packs: dict[str, str] | None = None,
    aptitudes: dict[str, int] | None = None,
    aptitude_template: str | None = None,
    flex_points: int | str | None = None,
    primary_morph: str | None = None,
    reputations: dict[str, int] | None = None,
    motivation_primary: dict[str, Any] | None = None,
    sync_linked_names: bool = True,
    sync_to_narratives: bool = False,
    acknowledge_only: bool = False,
    source: str = "web",
) -> tuple[GeneratedCharacter, list[str]]:
    """Update Point-Buy profile & mechanical tools directly on a GeneratedCharacter.

    Supports identity fields, skillPacks, aptitudes/template/flex, primary morph,
    reputation scores, primary motivation, and languages, keeping summary, PointBuyExported
    payload, MeshNet sync metadata, and optionally Census/Dossier narratives in sync.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required.")
    if character.user_id != user.pk and not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        raise ValueError("You do not have permission to update this character sheet.")

    raw_data = ensure_valid_point_buy_payload(
        character.raw_data if isinstance(character.raw_data, dict) else {},
        character_name=character.character_name,
    )
    pb = raw_data["pointBuy"]

    changed_fields: list[str] = []
    new_char_name = character.character_name

    if not acknowledge_only:
        text_field_map = [
            ("name", character_name, "Character Name"),
            ("fullName", full_name, "Full Name"),
            ("concept", concept, "Concept"),
            ("egoType", ego_type, "Ego Type"),
            ("gender", gender, "Gender"),
            ("museName", muse_name, "Muse Name"),
        ]
        for pb_key, incoming, label in text_field_map:
            if incoming is None:
                continue
            cleaned = str(incoming).strip()
            existing_val = _unwrap_tagged_text(pb.get(pb_key))
            if cleaned != existing_val:
                pb[pb_key] = _encode_tagged_input(cleaned)
                changed_fields.append(label)
            elif pb_key not in pb and cleaned:
                pb[pb_key] = _encode_tagged_input(cleaned)

        if description is not None:
            desc_clean = str(description).strip()
            existing_desc = _unwrap_tagged_text(pb.get("description"))
            if desc_clean != existing_desc:
                pb["description"] = f"h_{desc_clean}" if desc_clean else "h_"
                changed_fields.append("Description")

        if languages is not None:
            if isinstance(languages, str):
                lang_items = [part.strip() for part in languages.split(",") if part.strip()]
            elif isinstance(languages, list):
                lang_items = [str(part).strip() for part in languages if str(part).strip()]
            else:
                lang_items = []
            # Deduplicate preserving order
            dedup_langs: list[str] = []
            seen_l: set[str] = set()
            for item in lang_items:
                if item.casefold() not in seen_l:
                    seen_l.add(item.casefold())
                    dedup_langs.append(item)
            old_langs = [_unwrap_tagged_text(x) for x in (pb.get("languages") or []) if _unwrap_tagged_text(x)]
            if dedup_langs != old_langs:
                pb["languages"] = [_encode_tagged_input(x) for x in dedup_langs[:15]]
                changed_fields.append("Languages")

        if character_name is not None and str(character_name).strip():
            new_char_name = str(character_name).strip()[:160]

        if aptitude_template is not None:
            tpl_needle = str(aptitude_template or "").strip()
            if not tpl_needle:
                if "aptitudeTemplate" in pb:
                    pb.pop("aptitudeTemplate", None)
                    changed_fields.append("Aptitude Template")
            else:
                tpl = next((t for t in APTITUDE_TEMPLATES if t["key"] == tpl_needle or t["name"].casefold() == tpl_needle.casefold()), None)
                if tpl is None:
                    raise ValueError(f"Unknown aptitude template '{tpl_needle}'.")
                cur_apts_before = pb.get("aptitudes") if isinstance(pb.get("aptitudes"), dict) else {}
                tpl_changed = pb.get("aptitudeTemplate") != tpl["key"]
                if tpl_changed:
                    pb["aptitudeTemplate"] = tpl["key"]
                    changed_fields.append(f"Aptitude Template ({tpl['name']})")
                # Apply template aptitudes if no explicit override OR form submitted unchanged prior values alongside a new template
                apts_unchanged = bool(aptitudes) and all(
                    int(aptitudes.get(k, cur_apts_before.get(k, 15))) == int(cur_apts_before.get(k, 15))
                    for k in ("cog", "int", "ref", "sav", "som", "wil")
                )
                if not aptitudes or (tpl_changed and apts_unchanged):
                    pb["aptitudes"] = dict(tpl["aptitudes"])
                    aptitudes = None
                    if "Aptitudes" not in changed_fields:
                        changed_fields.append("Aptitudes")

        if isinstance(aptitudes, dict) and aptitudes:
            cur_apts = pb.get("aptitudes") if isinstance(pb.get("aptitudes"), dict) else {}
            next_apts = {k: int(cur_apts.get(k, 15)) for k in ("cog", "int", "ref", "sav", "som", "wil")}
            apt_changed = False
            for k in ("cog", "int", "ref", "sav", "som", "wil"):
                if k in aptitudes and aptitudes[k] is not None:
                    clamped = max(5, min(30, int(aptitudes[k])))
                    if next_apts[k] != clamped:
                        next_apts[k] = clamped
                        apt_changed = True
            if apt_changed:
                pb["aptitudes"] = next_apts
                if "Aptitudes" not in changed_fields:
                    changed_fields.append("Aptitudes")

        if flex_points is not None and str(flex_points).strip() != "":
            try:
                clamped_flex = max(0, min(3, int(flex_points)))
            except (TypeError, ValueError) as exc:
                raise ValueError("Flex points must be an integer between 0 and 3.") from exc
            if pb.get("flexPoints") != clamped_flex:
                pb["flexPoints"] = clamped_flex
                changed_fields.append("Flex Points")

        if primary_morph is not None:
            req_morph = str(primary_morph or "").strip()
            cur_morphs = pb.get("morphs") if isinstance(pb.get("morphs"), dict) else {}
            first_key = next(iter(cur_morphs), None)
            first_label = _extract_design_label(cur_morphs[first_key], raw_data.get("packs") or {}) if first_key else ""
            if not req_morph:
                if first_key:
                    cur_morphs.pop(first_key, None)
                    pb["morphs"] = cur_morphs
                    changed_fields.append("Morph")
            else:
                morph_opt = _find_morph_option(req_morph)
                if morph_opt is None:
                    raise ValueError(f"Unknown morph option: '{req_morph}'.")
                if morph_opt["name"].casefold() != first_label.casefold():
                    slot_key = first_key or "m1"
                    dtype = morph_opt["design_type"]
                    morph_entry: dict[str, Any] = {
                        "type": dtype,
                        "design": {"uid": morph_opt["uid"]},
                        "rechargeState": {},
                        "spentPools": {},
                    }
                    if dtype == "digitalForm":
                        morph_entry["meshHealthState"] = {}
                    else:
                        morph_entry["physicalHealthState"] = {}
                    if dtype == "biologicalBody":
                        morph_entry["sex"] = "i_"
                    cur_morphs[slot_key] = morph_entry
                    pb["morphs"] = cur_morphs
                    _embed_morph_pack_design(raw_data, morph_opt)
                    changed_fields.append(f"Morph ({morph_opt['name']})")

        if isinstance(reputations, dict):
            cur_reps = pb.get("reputations") if isinstance(pb.get("reputations"), dict) else {}
            rep_choices = get_sheet_rep_choices()
            rep_lookup = {r["key"].casefold(): r for r in rep_choices}
            rep_lookup.update({r["name"].casefold(): r for r in rep_choices})
            rep_changed = False
            for r_needle, pts_raw in reputations.items():
                opt = rep_lookup.get(str(r_needle or "").strip().casefold()) or _find_rep_option(str(r_needle or ""))
                if opt is None:
                    continue
                if pts_raw is None or str(pts_raw).strip() == "":
                    continue
                pts = max(-100, min(100, int(pts_raw)))
                existing_key = next(
                    (
                        k for k, v in cur_reps.items()
                        if isinstance(v, dict)
                        and isinstance(v.get("design"), dict)
                        and (
                            v["design"].get("uid") == opt["uid"]
                            or str(v["design"].get("uid") or "").endswith(f":{opt['key']}")
                        )
                    ),
                    None,
                )
                target_key = existing_key or f"rep_{opt['key']}"
                if pts == 0 and existing_key is None:
                    continue
                old_pts = cur_reps.get(target_key, {}).get("points") if existing_key else None
                if old_pts != pts:
                    cur_reps[target_key] = {
                        "design": {"uid": opt["uid"]},
                        "isTracked": True,
                        "points": pts,
                        "spentFavors": (cur_reps.get(target_key, {}) or {}).get("spentFavors") or {},
                    }
                    rep_changed = True
            if rep_changed:
                pb["reputations"] = cur_reps
                changed_fields.append("Reputations")

        if isinstance(motivation_primary, dict):
            cause_text = str(motivation_primary.get("cause") or "").strip()
            support_cause = bool(motivation_primary.get("support_cause", True))
            cur_mots = pb.get("motivations") if isinstance(pb.get("motivations"), dict) else {}
            first_mot_key = next(iter(cur_mots), None) or "mot1"
            if cause_text:
                existing_mot = cur_mots.get(first_mot_key) if isinstance(cur_mots.get(first_mot_key), dict) else {}
                old_cause = _unwrap_tagged_text(existing_mot.get("cause"))
                old_support = bool(existing_mot.get("supportCause", True))
                if cause_text != old_cause or support_cause != old_support or first_mot_key not in cur_mots:
                    cur_mots[first_mot_key] = {
                        "cause": _encode_tagged_input(cause_text),
                        "description": existing_mot.get("description") or "h_",
                        "goals": existing_mot.get("goals") if isinstance(existing_mot.get("goals"), dict) else {},
                        "supportCause": support_cause,
                    }
                    pb["motivations"] = cur_mots
                    changed_fields.append("Motivations")

        if isinstance(skill_packs, dict):
            pb_packs = pb.get("skillPacks") if isinstance(pb.get("skillPacks"), dict) else {}
            pb["skillPacks"] = pb_packs
            raw_packs = raw_data.get("packs") if isinstance(raw_data.get("packs"), dict) else {}
            design_lookup = _load_meshnet_design_lookup()

            for slot in ("background", "career", "interest", "faction"):
                if slot not in skill_packs:
                    continue
                requested = str(skill_packs.get(slot) or "").strip()
                current_entry = pb_packs.get(slot)
                current_label = _extract_design_label(current_entry, raw_packs) if current_entry else ""

                if not requested:
                    if slot in pb_packs:
                        pb_packs.pop(slot, None)
                        changed_fields.append(slot.title())
                    continue

                opt = _find_skill_pack_option(slot, requested)
                if opt is None:
                    raise ValueError(f"Unknown {slot} skill pack option: '{requested}'.")

                if opt["name"].casefold() != current_label.casefold():
                    pb_packs[slot] = {
                        "design": {"uid": opt["uid"]},
                        "skills": {},
                    }
                    if isinstance(raw_packs, dict):
                        pack_bucket = raw_packs.setdefault(
                            opt["pack"],
                            {"name": "i_EP2e Core Rulebook", "designs": {}},
                        )
                        designs_bucket = pack_bucket.setdefault("designs", {})
                        sp_bucket = designs_bucket.setdefault("skillPack", {})
                        row = design_lookup.get(opt["key"])
                        if row and isinstance(row.get("system"), dict):
                            sys_copy = copy.deepcopy(row["system"])
                            if isinstance(sys_copy.get("name"), str) and sys_copy["name"].startswith("m_"):
                                sys_copy["name"] = _encode_tagged_input(opt["name"])
                            sp_bucket[opt["key"]] = sys_copy
                        else:
                            sp_bucket[opt["key"]] = {
                                "name": _encode_tagged_input(opt["name"]),
                                "description": "h_",
                                "skillPackType": slot,
                                "type": "skillPack",
                                "ratings": {},
                                "references": [],
                            }
                        raw_data["packs"] = raw_packs
                    changed_fields.append(f"{slot.title()} ({opt['name']})")

    now_iso = timezone.now().isoformat()
    sync_meta = raw_data.get("spacemarchesSync") if isinstance(raw_data.get("spacemarchesSync"), dict) else {}
    sync_meta.update(
        {
            "last_synced_at": now_iso,
            "acknowledged_at": now_iso,
            "updated_from": str(source or "web"),
            "changed_fields": changed_fields,
        }
    )
    raw_data["spacemarchesSync"] = sync_meta

    summary = extract_point_buy_summary(raw_data)
    summary["character_name"] = new_char_name
    if not summary.get("character_name"):
        summary["character_name"] = character.character_name

    with transaction.atomic():
        character.character_name = new_char_name
        character.raw_data = raw_data
        character.summary = summary
        character.save(update_fields=["character_name", "raw_data", "summary", "updated_at"])

        if sync_linked_names and character_name is not None and str(character_name).strip():
            if character.dossier_id and character.dossier is not None:
                if character.dossier.character_name != new_char_name:
                    character.dossier.character_name = new_char_name
                    character.dossier.save(update_fields=["character_name", "updated_at"])
            for census in EclipsePhaseCensus.objects.filter(character=character):
                if census.character_name != new_char_name:
                    census.character_name = new_char_name
                    census.save(update_fields=["character_name", "updated_at"])

        if sync_to_narratives and changed_fields:
            from spacemarches.services.character_cross_sync import sync_sheet_updates_to_narratives

            sync_sheet_updates_to_narratives(character, changed_fields)

    return character, changed_fields
