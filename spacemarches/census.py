"""Loader and chapter/question helpers for the Eclipse Phase Census (ShadowDragon8685 / GearheadLydia)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "fixtures" / "ep_census_schema.json"


@lru_cache(maxsize=1)
def load_census_schema() -> dict[str, Any]:
    """Load and cache the parsed Eclipse Phase Census JSON schema."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _chapter_index() -> dict[str, dict[str, Any]]:
    return {str(ch["id"]): ch for ch in load_census_schema().get("chapters", [])}


@lru_cache(maxsize=1)
def _question_index() -> dict[str, dict[str, Any]]:
    return {str(q["id"]): q for q in load_census_schema().get("questions", [])}


def get_census_meta() -> dict[str, Any]:
    """Return top-level Census framing, intro paragraphs, notices, tracked changes, and CC legalese."""
    schema = load_census_schema()
    return {
        "schema_version": schema.get("schema_version", "1.0"),
        "title": schema.get("title", "Eclipse Phase Census"),
        "subtitle": schema.get("subtitle", ""),
        "source_title": schema.get("source_title", ""),
        "source_credits": schema.get("source_credits", ""),
        "license": schema.get("license", "CC BY-NC-SA 3.0"),
        "attribution_notice": schema.get("attribution_notice", ""),
        "intro_paragraphs": list(schema.get("intro_paragraphs", [])),
        "appendix_notice": list(schema.get("appendix_notice", [])),
        "tracked_changes": list(schema.get("tracked_changes", [])),
        "legal_notice": list(schema.get("legal_notice", [])),
    }


def get_census_attribution() -> str:
    return str(load_census_schema().get("attribution_notice", ""))


def get_census_chapters(*, include_appendix: bool = True) -> list[dict[str, Any]]:
    chapters = []
    for ch in load_census_schema().get("chapters", []):
        if not include_appendix and ch.get("is_appendix"):
            continue
        chapters.append(dict(ch))
    return chapters


def get_census_chapter(chapter_id: str) -> dict[str, Any] | None:
    ch = _chapter_index().get(str(chapter_id))
    return dict(ch) if ch is not None else None


def get_census_question(question_id: str) -> dict[str, Any] | None:
    q = _question_index().get(str(question_id))
    return dict(q) if q is not None else None


def is_valid_census_question_id(question_id: str, *, answerable_only: bool = False) -> bool:
    q = _question_index().get(str(question_id))
    if q is None:
        return False
    if answerable_only and not q.get("answerable", True):
        return False
    return True


def _question_visible(
    q: dict[str, Any],
    *,
    include_sexuality: bool = True,
    include_appendix: bool = True,
) -> bool:
    group = q.get("section_group", "main")
    if group == "moved_appendix" and not include_appendix:
        return False
    if group in ("sexuality_13c", "sexuality_13e") and not include_sexuality:
        return False
    return True


def get_all_census_questions(
    *,
    include_sexuality: bool = True,
    include_appendix: bool = True,
    answerable_only: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for q in load_census_schema().get("questions", []):
        if not _question_visible(
            q,
            include_sexuality=include_sexuality,
            include_appendix=include_appendix,
        ):
            continue
        if answerable_only and not q.get("answerable", True):
            continue
        results.append(dict(q))
    return results


def get_chapter_questions(
    chapter_id: str,
    *,
    include_sexuality: bool = True,
    include_appendix: bool = True,
    answerable_only: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for q in load_census_schema().get("questions", []):
        if q.get("chapter_id") != str(chapter_id):
            continue
        if not _question_visible(
            q,
            include_sexuality=include_sexuality,
            include_appendix=include_appendix,
        ):
            continue
        if answerable_only and not q.get("answerable", True):
            continue
        results.append(dict(q))
    return results
