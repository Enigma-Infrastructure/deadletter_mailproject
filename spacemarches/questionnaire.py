"""Cached accessors for the Eclipse Phase / Spacemarches character questionnaire schema."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "fixtures" / "ep_questionnaire_schema.json"


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _question_index() -> dict[str, dict[str, Any]]:
    schema = load_schema()
    return {item["id"]: item for item in schema.get("questions", [])}


def get_attribution_notice() -> str:
    return load_schema().get("attribution_notice", "")


def get_schema_metadata() -> dict[str, str]:
    schema = load_schema()
    return {
        "schema_version": schema.get("schema_version", "1.0"),
        "title": schema.get("title", ""),
        "license": schema.get("license", "CC BY-NC-SA 3.0"),
        "attribution_notice": schema.get("attribution_notice", ""),
    }


def get_all_questions(include_sensitive: bool = True) -> list[dict[str, Any]]:
    questions = load_schema().get("questions", [])
    if include_sensitive:
        return [dict(q) for q in questions]
    return [dict(q) for q in questions if q.get("tier") != "sensitive_appendix"]


def get_question(question_id: str) -> dict[str, Any] | None:
    item = _question_index().get(str(question_id))
    return dict(item) if item is not None else None


def is_valid_question_id(question_id: str) -> bool:
    return str(question_id) in _question_index()


def get_core_questions() -> list[dict[str, Any]]:
    return [dict(q) for q in load_schema().get("questions", []) if q.get("tier") == "core"]


def get_questions_by_tier(tier: str) -> list[dict[str, Any]]:
    return [dict(q) for q in load_schema().get("questions", []) if q.get("tier") == tier]


def get_children(parent_id: str, include_sensitive: bool = True) -> list[dict[str, Any]]:
    results = []
    for q in load_schema().get("questions", []):
        if q.get("parent_id") == parent_id:
            if not include_sensitive and q.get("tier") == "sensitive_appendix":
                continue
            results.append(dict(q))
    return results


def get_descendants(parent_id: str, include_sensitive: bool = True) -> list[dict[str, Any]]:
    """Return direct children plus nested children (e.g., 13d1-13d6 under 13) in schema order."""
    direct = get_children(parent_id, include_sensitive=include_sensitive)
    direct_ids = {q["id"] for q in direct}
    results = list(direct)
    if direct_ids:
        for q in load_schema().get("questions", []):
            if q.get("parent_id") in direct_ids:
                if not include_sensitive and q.get("tier") == "sensitive_appendix":
                    continue
                results.append(dict(q))
    return results


def get_categories(include_sensitive: bool = True) -> list[str]:
    seen: set[str] = set()
    categories: list[str] = []
    for q in get_all_questions(include_sensitive=include_sensitive):
        cat = q.get("category", "")
        if cat and cat not in seen:
            seen.add(cat)
            categories.append(cat)
    return categories


TEMPORAL_SCOPE_LABELS = {
    "origin": "Origin (Pre-Fall Default; Post-Fall if AGI/Uplift/Lost)",
    "fall": "Fall Era",
    "present": "Now (Nominal 10.000 AF)",
    "timeless": "Voice & OOC",
}


def get_question_temporal_defaults(question_id: str) -> dict[str, str]:
    """Return the prompt's natural temporal scope and default (era, sol_number)."""
    q = get_question(question_id)
    if q is None:
        return {
            "temporal_scope": "present",
            "temporal_scope_label": TEMPORAL_SCOPE_LABELS["present"],
            "default_stardate_era": "post_fall",
            "default_sol_number": "10.000",
        }
    scope = str(q.get("temporal_scope") or "present")
    era = str(q.get("default_stardate_era") or "post_fall")
    sol_number = str(q.get("default_sol_number") or ("10.000" if era == "post_fall" else ""))
    return {
        "temporal_scope": scope,
        "temporal_scope_label": TEMPORAL_SCOPE_LABELS.get(scope, TEMPORAL_SCOPE_LABELS["present"]),
        "default_stardate_era": era,
        "default_sol_number": sol_number,
    }
