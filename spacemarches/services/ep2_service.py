"""Helpers for sanitizing, summarizing, and querying seeded Ep2Entry reference records."""

from __future__ import annotations

import html
import json
import re
from typing import Any

import nh3
from django.db.models import Case, Count, IntegerField, QuerySet, When

from spacemarches.models import Ep2Entry

EP2_CATEGORY_ORDER = [choice[0] for choice in Ep2Entry.CATEGORY_CHOICES]

_SOURCE_URL_MAP = {
    "bubz-ep2e": "https://github.com/Bubz43/ep2e/tree/master/src/packs",
    "mesh-net": "https://github.com/TheGam1ngWizard/mesh-net",
    "ep2e-virtual": "https://github.com/TheGam1ngWizard/ep2e-virtual",
    "spacemarches": "",
    "custom": "",
}

_ALLOWED_TAGS = {
    "p",
    "br",
    "em",
    "strong",
    "b",
    "i",
    "ul",
    "ol",
    "li",
    "div",
    "span",
    "h3",
    "h4",
    "code",
    "pre",
    "blockquote",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def get_ep2_source_url(source: str | None) -> str:
    """Resolve upstream attribution URL for a given Ep2Entry.source key."""
    key = (source or "").strip().lower()
    return _SOURCE_URL_MAP.get(key, "")


def format_pack_label(pack: str | None) -> str:
    """Turn a pack slug like 'combat-augmentations' into 'Combat Augmentations'."""
    raw = (pack or "").strip()
    if not raw:
        return "General"
    acronyms = {"qe": "QE", "psi": "Psi", "ep2": "EP2", "ali": "ALI"}
    parts = [acronyms.get(p.lower(), p.capitalize()) for p in raw.split("-") if p]
    return " ".join(parts)


def order_ep2_queryset(qs: QuerySet[Ep2Entry]) -> QuerySet[Ep2Entry]:
    """Order Ep2Entry rows with player-first categories before NPC/creature entries."""
    category_rank = Case(
        *[When(category=cat, then=idx) for idx, cat in enumerate(EP2_CATEGORY_ORDER)],
        default=len(EP2_CATEGORY_ORDER),
        output_field=IntegerField(),
    )
    return qs.order_by(category_rank, "pack", "name")


def sanitize_ep2_html(raw_html: str | None) -> str:
    """Sanitize Foundry pack HTML descriptions with nh3 before rendering."""
    text = (raw_html or "").strip()
    if not text:
        return ""
    cleaned = nh3.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes={},
    )
    return cleaned.strip()


def strip_ep2_text(raw_html: str | None, *, max_length: int = 220) -> str:
    """Return plain-text excerpt from Foundry HTML description."""
    raw = (raw_html or "").strip()
    if not raw:
        return ""
    # Clean first, then strip tags and decode HTML entities
    cleaned = sanitize_ep2_html(raw)
    plain = _HTML_TAG_RE.sub(" ", cleaned)
    plain = html.unescape(plain)
    plain = _WHITESPACE_RE.sub(" ", plain).strip()
    if max_length and len(plain) > max_length:
        return plain[: max_length - 1].rstrip() + "…"
    return plain


def _format_bool(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def extract_ep2_highlights(entry: Ep2Entry) -> list[dict[str, str]]:
    """Extract concise, typed stat highlights from Ep2Entry.system based on category."""
    sys_data = entry.system if isinstance(entry.system, dict) else {}
    highlights: list[dict[str, str]] = []

    def add(label: str, val: Any) -> None:
        if val is None:
            return
        text = str(val).strip()
        if text:
            highlights.append({"label": label, "value": text})

    cat = entry.category

    if cat == Ep2Entry.CATEGORY_MORPH:
        add("Subtype", sys_data.get("subtype") or entry.entry_type)
        acq = sys_data.get("acquisition")
        if isinstance(acq, dict):
            if acq.get("cost") is not None:
                add("MP Cost", acq.get("cost"))
            if acq.get("availability") is not None:
                add("Availability", acq.get("availability"))
            if acq.get("complexity"):
                add("Complexity", str(acq.get("complexity")).title())
            if acq.get("restricted"):
                add("Restricted", "Yes")
        pools = sys_data.get("pools")
        if isinstance(pools, dict):
            pool_bits = [
                f"{k[:3].upper()} {pools[k]}"
                for k in ("insight", "moxie", "vigor", "flex")
                if pools.get(k) is not None
            ]
            if pool_bits:
                add("Pools", " / ".join(pool_bits))
        moves = sys_data.get("movementRates")
        if isinstance(moves, list) and moves:
            move_bits = []
            for m in moves[:3]:
                if isinstance(m, dict) and m.get("type"):
                    move_bits.append(f"{str(m['type']).title()} {m.get('base', '?')}/{m.get('full', '?')}")
            if move_bits:
                add("Movement", ", ".join(move_bits))
        if sys_data.get("size"):
            add("Size", str(sys_data.get("size")).title())
        if sys_data.get("unarmedDV"):
            add("Unarmed DV", sys_data.get("unarmedDV"))

    elif cat == Ep2Entry.CATEGORY_GEAR:
        if sys_data.get("complexity"):
            add("Complexity", str(sys_data.get("complexity")).title())
        if sys_data.get("restricted"):
            add("Restricted", "Yes")
        if sys_data.get("quality") and str(sys_data.get("quality")) != "average":
            add("Quality", str(sys_data.get("quality")).title())
        armor = sys_data.get("armorValues")
        if isinstance(armor, dict):
            e_val = armor.get("energy")
            k_val = armor.get("kinetic")
            if e_val is not None or k_val is not None:
                add("Armor (E/K)", f"{e_val or 0} / {k_val or 0}")
        primary = sys_data.get("primaryAttack")
        if isinstance(primary, dict):
            dmg = primary.get("damageFormula")
            if dmg:
                ap_tag = " (AP)" if primary.get("armorPiercing") else ""
                add("Damage", f"{dmg}{ap_tag}")
            modes = primary.get("firingModes")
            if isinstance(modes, list) and modes:
                add("Firing Modes", ", ".join(str(m).upper() for m in modes))
        if sys_data.get("range"):
            add("Range", f"{sys_data.get('range')} m")
        if sys_data.get("softwareType"):
            add("Software", str(sys_data.get("softwareType")).title())
        if sys_data.get("category") and isinstance(sys_data.get("category"), str):
            add("Ware", sys_data.get("category"))

    elif cat == Ep2Entry.CATEGORY_TRAIT:
        if sys_data.get("traitType"):
            add("Polarity", str(sys_data.get("traitType")).title())
        if sys_data.get("subtype"):
            add("Applies To", str(sys_data.get("subtype")).title())
        levels = sys_data.get("levels")
        if isinstance(levels, list) and levels:
            costs = [str(lv.get("cost")) for lv in levels if isinstance(lv, dict) and lv.get("cost") is not None]
            if costs:
                add("Cost", " / ".join(costs))
        if sys_data.get("restrictions"):
            add("Restrictions", sys_data.get("restrictions"))
        if sys_data.get("triggers"):
            add("Triggers", sys_data.get("triggers"))

    elif cat == Ep2Entry.CATEGORY_SLEIGHT:
        if sys_data.get("sleightType"):
            add("Type", str(sys_data.get("sleightType")).title())
        if sys_data.get("action"):
            add("Action", str(sys_data.get("action")).title())
        if sys_data.get("duration"):
            add("Duration", str(sys_data.get("duration")))
        if sys_data.get("infectionMod") is not None:
            add("Infection Mod", sys_data.get("infectionMod"))

    elif cat == Ep2Entry.CATEGORY_SUBSTANCE:
        if sys_data.get("substanceType"):
            add("Type", str(sys_data.get("substanceType")).title())
        if sys_data.get("classification"):
            add("Class", str(sys_data.get("classification")).title())
        if sys_data.get("complexity"):
            add("Complexity", str(sys_data.get("complexity")).title())
        if sys_data.get("restricted"):
            add("Restricted", "Yes")
        if sys_data.get("addiction"):
            add("Addiction", f"{sys_data.get('addiction')} ({sys_data.get('addictionMod', 0)})")

    elif cat == Ep2Entry.CATEGORY_CHARACTER:
        if sys_data.get("egoType"):
            add("Ego Type", str(sys_data.get("egoType")).title())
        apts = sys_data.get("aptitudes")
        if isinstance(apts, dict):
            apt_bits = [
                f"{k.upper()} {apts[k]}"
                for k in ("cog", "int", "ref", "sav", "som", "wil")
                if apts.get(k) is not None
            ]
            if apt_bits:
                add("Aptitudes", " · ".join(apt_bits))
        if sys_data.get("flex") is not None:
            add("Flex", sys_data.get("flex"))

    elif cat == Ep2Entry.CATEGORY_SPECIAL:
        if sys_data.get("strain"):
            add("Strain", sys_data.get("strain"))
        if sys_data.get("level") is not None:
            add("Level", sys_data.get("level"))
        if sys_data.get("requireBioSubstrate") is not None:
            add("Bio-Substrate", _format_bool(sys_data.get("requireBioSubstrate")))

    return highlights[:8]


def format_ep2_system_json(entry: Ep2Entry) -> str:
    """Return pretty-printed JSON of Ep2Entry.system for inspection views."""
    payload = entry.system if isinstance(entry.system, (dict, list)) else {}
    return json.dumps(payload, indent=2, ensure_ascii=False)


def get_ep2_catalog_summary(
    *,
    selected_category: str = "",
    selected_design_pack: str = "",
    include_storyteller: bool = False,
    user=None,
) -> dict[str, Any]:
    """Return category, sub-pack, and DesignPack breakdowns for visible Ep2Entry rows."""
    from spacemarches.services.design_pack_service import (
        get_design_packs_with_counts,
        visible_ep2_entries_qs,
    )

    base_qs = visible_ep2_entries_qs(user, include_storyteller=include_storyteller)
    if selected_design_pack:
        base_qs = base_qs.filter(design_pack__slug=selected_design_pack)

    total_entries = base_qs.count()
    cat_counts_raw = {
        row["category"]: row["total"]
        for row in base_qs.values("category").annotate(total=Count("id"))
    }
    categories = [
        {
            "value": value,
            "label": label,
            "count": cat_counts_raw.get(value, 0),
        }
        for value, label in Ep2Entry.CATEGORY_CHOICES
        if cat_counts_raw.get(value, 0) > 0
    ]

    packs_qs = base_qs
    if selected_category:
        packs_qs = packs_qs.filter(category=selected_category)
    category_labels = dict(Ep2Entry.CATEGORY_CHOICES)
    packs = [
        {
            "pack": row["pack"],
            "label": format_pack_label(row["pack"]),
            "category": row["category"],
            "category_label": category_labels.get(row["category"], row["category"]),
            "count": row["total"],
        }
        for row in packs_qs.values("pack", "category").annotate(total=Count("id")).order_by("pack")
    ]
    all_pack_count = base_qs.values("pack").distinct().count()

    design_packs = get_design_packs_with_counts(user, include_storyteller=include_storyteller)
    storyteller_hidden_count = 0
    if not include_storyteller:
        all_visible_qs = visible_ep2_entries_qs(user, include_storyteller=True)
        if selected_design_pack:
            all_visible_qs = all_visible_qs.filter(design_pack__slug=selected_design_pack)
        storyteller_hidden_count = max(0, all_visible_qs.count() - total_entries)

    return {
        "total_entries": total_entries,
        "pack_count": all_pack_count,
        "categories": categories,
        "packs": packs,
        "design_packs": design_packs,
        "storyteller_hidden_count": storyteller_hidden_count,
        "include_storyteller": include_storyteller,
    }
