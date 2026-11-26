"""Service layer for Eclipse Phase Census walkthroughs, answers, stats, and exports."""

from __future__ import annotations

import html
from typing import Any

from django.utils import timezone

from spacemarches.markdown_utils import render_markdown_inline_safe
from spacemarches.census import (
    get_all_census_questions,
    get_census_attribution,
    get_census_chapters,
    get_census_meta,
    get_census_question,
    get_chapter_questions,
)
from spacemarches.models import CharacterDossier, EclipsePhaseCensus, GeneratedCharacter


def _normalize_entry_voice(raw_voice: str, default_voice: str = "first_person") -> str:
    cleaned = str(raw_voice or "").strip().lower()
    if cleaned in ("first_person", "first-person", "1st", "first"):
        return "first_person"
    if cleaned in ("omniscient", "third_person", "third-person", "3rd"):
        return "omniscient"
    return "omniscient" if str(default_voice).lower() == "omniscient" else "first_person"


def _normalize_model_voice(raw_voice: str) -> str:
    cleaned = str(raw_voice or "").strip().upper()
    if cleaned == EclipsePhaseCensus.VOICE_OMNISCIENT or cleaned == "OMNISCIENT":
        return EclipsePhaseCensus.VOICE_OMNISCIENT
    return EclipsePhaseCensus.VOICE_FIRST_PERSON


def _default_entry_voice_for(census: EclipsePhaseCensus) -> str:
    return (
        "omniscient"
        if census.narrative_voice == EclipsePhaseCensus.VOICE_OMNISCIENT
        else "first_person"
    )


def normalize_census_record(
    record: Any,
    *,
    default_voice: str = "first_person",
) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {"answer": "", "voice": default_voice, "updated_at": ""}
    return {
        "answer": str(record.get("answer") or ""),
        "voice": _normalize_entry_voice(str(record.get("voice") or ""), default_voice=default_voice),
        "updated_at": str(record.get("updated_at") or ""),
    }


def create_census(
    user,
    *,
    character_name: str = "",
    narrative_voice: str = EclipsePhaseCensus.VOICE_FIRST_PERSON,
    dossier: CharacterDossier | None = None,
    character: GeneratedCharacter | None = None,
    show_sexuality_sections: bool = True,
    show_sensitive_appendix: bool = False,
) -> EclipsePhaseCensus:
    if dossier is not None and dossier.user_id not in (None, user.pk) and not (
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
    ):
        raise ValueError("Selected Character Dossier is not accessible to this user.")
    if character is not None and character.user_id != user.pk:
        raise ValueError("Selected Character Sheet does not belong to this user.")

    resolved_name = (character_name or "").strip()
    if not resolved_name and dossier is not None:
        resolved_name = dossier.character_name
    if not resolved_name and character is not None:
        resolved_name = character.character_name
    if not resolved_name:
        raise ValueError("Character name is required to initialize an Eclipse Phase Census.")

    if character is not None and dossier is None and character.dossier_id:
        dossier = character.dossier

    return EclipsePhaseCensus.objects.create(
        user=user,
        dossier=dossier,
        character=character,
        character_name=resolved_name[:160],
        narrative_voice=_normalize_model_voice(narrative_voice),
        responses={},
        show_sexuality_sections=bool(show_sexuality_sections),
        show_sensitive_appendix=bool(show_sensitive_appendix),
    )


def save_census_answer(
    census: EclipsePhaseCensus,
    question_id: str,
    answer: str,
    *,
    voice: str = "",
) -> dict[str, Any]:
    q = get_census_question(question_id)
    if q is None:
        raise ValueError(f"Unknown Eclipse Phase Census question id '{question_id}'.")
    if not q.get("answerable", True):
        raise ValueError(f"Census section '{question_id}' is informational only and does not accept an answer.")

    responses = dict(census.responses or {}) if isinstance(census.responses, dict) else {}
    cleaned_answer = (answer or "").strip()
    default_voice = _default_entry_voice_for(census)
    norm_voice = _normalize_entry_voice(voice, default_voice=default_voice)

    if not cleaned_answer:
        responses.pop(q["id"], None)
        census.responses = responses
        census.save(update_fields=["responses", "updated_at"])
        return {
            "question_id": q["id"],
            "answered": False,
            "answer": "",
            "voice": norm_voice,
            "updated_at": "",
        }

    record = {
        "answer": cleaned_answer,
        "voice": norm_voice,
        "updated_at": timezone.now().isoformat(),
    }
    responses[q["id"]] = record
    census.responses = responses
    census.save(update_fields=["responses", "updated_at"])
    return {
        "question_id": q["id"],
        "answered": True,
        **record,
    }


def compute_census_stats(census: EclipsePhaseCensus) -> dict[str, Any]:
    responses = census.responses if isinstance(census.responses, dict) else {}
    include_sexuality = bool(census.show_sexuality_sections)
    include_appendix = bool(census.show_sensitive_appendix)

    def _is_answered(qid: str) -> bool:
        rec = responses.get(qid)
        return isinstance(rec, dict) and bool(str(rec.get("answer", "")).strip())

    chapters = get_census_chapters(include_appendix=True)
    chapter_stats: list[dict[str, Any]] = []
    total_answerable = 0
    total_answered = 0

    for ch in chapters:
        ch_included = include_appendix or not ch.get("is_appendix")
        qs = get_chapter_questions(
            ch["id"],
            include_sexuality=include_sexuality,
            include_appendix=True,
            answerable_only=True,
        )
        q_count = len(qs)
        a_count = sum(1 for q in qs if _is_answered(q["id"]))
        pct = int(round((a_count / q_count) * 100)) if q_count else 0
        if ch_included:
            total_answerable += q_count
            total_answered += a_count
        chapter_stats.append(
            {
                "id": ch["id"],
                "number": ch["number"],
                "title": ch["title"],
                "description": ch["description"],
                "is_appendix": bool(ch.get("is_appendix")),
                "is_enabled": ch_included,
                "answered_count": a_count,
                "total_questions": q_count,
                "completion_percent": pct,
            }
        )

    overall_pct = int(round((total_answered / total_answerable) * 100)) if total_answerable else 0
    return {
        "answered_count": total_answered,
        "total_questions": total_answerable,
        "completion_percent": overall_pct,
        "chapters": chapter_stats,
    }


def export_census_markdown(census: EclipsePhaseCensus, *, include_unanswered: bool = False) -> str:
    meta = get_census_meta()
    responses = census.responses if isinstance(census.responses, dict) else {}
    default_voice = _default_entry_voice_for(census)
    include_sexuality = bool(census.show_sexuality_sections)
    include_appendix = bool(census.show_sensitive_appendix)

    lines = [
        f"# Eclipse Phase Character Questionnaire: {census.character_name}",
        f"_{meta.get('source_credits') or '(Original By ShadowDragon8685 / Edited Copy by GearheadLydia)'}_",
        "",
        f"- **Default Narrative Voice:** {census.get_narrative_voice_display()}",
        f"- **Owner:** {census.user}",
    ]
    if census.dossier_id and census.dossier:
        lines.append(f"- **Linked Operational Dossier:** {census.dossier.character_name}")
    if census.character_id and census.character:
        lines.append(f"- **Linked Point-Buy Sheet:** {census.character.character_name}")
    lines.append("")

    if include_unanswered and meta.get("intro_paragraphs"):
        lines.extend(["## Introduction", ""])
        for p in meta["intro_paragraphs"]:
            lines.extend([p, ""])

    chapters = get_census_chapters(include_appendix=include_appendix)
    any_written = False

    for ch in chapters:
        qs = get_chapter_questions(
            ch["id"],
            include_sexuality=include_sexuality,
            include_appendix=include_appendix,
            answerable_only=False,
        )
        chapter_items: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for q in qs:
            if not q.get("answerable", True):
                if include_unanswered:
                    chapter_items.append((q, None))
                continue
            rec = responses.get(q["id"])
            norm = normalize_census_record(rec, default_voice=default_voice)
            if norm["answer"].strip():
                chapter_items.append((q, norm))
            elif include_unanswered:
                chapter_items.append((q, None))

        if not chapter_items:
            continue

        any_written = True
        lines.extend([f"## {ch['number']} — {ch['title']}", ""])
        if ch.get("is_appendix") and meta.get("appendix_notice"):
            for p in meta["appendix_notice"]:
                lines.extend([f"> {p}", ""])

        for q, norm in chapter_items:
            disp_id = q.get("display_id") or q["id"]
            voice_tag = ""
            if norm is not None:
                vlabel = "First-person" if norm["voice"] == "first_person" else "Omniscient"
                voice_tag = f" _({vlabel})_"
            lines.append(f"### {disp_id}: {q['heading']}{voice_tag}")
            lines.append("")
            if q.get("primer"):
                lines.append(q["primer"])
                lines.append("")
            if norm is not None:
                lines.append(norm["answer"].strip())
                lines.append("")
            elif include_unanswered:
                lines.append("_[Unanswered]_")
                lines.append("")

    if not any_written:
        lines.extend(["_No Census questions answered yet._", ""])

    lines.extend(["---", "", "## Attribution & Creative Commons Notice", ""])
    lines.append(get_census_attribution())
    lines.append("")
    for p in meta.get("legal_notice", []):
        lines.extend([p, ""])
    return "\n".join(lines)


def export_census_html(census: EclipsePhaseCensus, *, include_unanswered: bool = False) -> str:
    meta = get_census_meta()
    responses = census.responses if isinstance(census.responses, dict) else {}
    default_voice = _default_entry_voice_for(census)
    include_sexuality = bool(census.show_sexuality_sections)
    include_appendix = bool(census.show_sensitive_appendix)
    stats = compute_census_stats(census)

    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(census.character_name)} — Eclipse Phase Census</title>",
        "<style>",
        "body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.55; color: #1a1f29; background: #f8f9fb; }",
        "header { border-bottom: 2px solid #2b3446; padding-bottom: 1rem; margin-bottom: 1.5rem; }",
        "h1 { margin: 0 0 0.25rem; font-size: 1.75rem; }",
        "h2 { margin-top: 2rem; border-bottom: 1px solid #cbd5e1; padding-bottom: 0.3rem; font-size: 1.25rem; }",
        ".meta { color: #475569; font-size: 0.9rem; margin: 0.25rem 0; }",
        ".card { background: #ffffff; border: 1px solid #dbe2ea; border-radius: 8px; padding: 1rem 1.15rem; margin: 0.9rem 0; }",
        ".q-head { font-weight: 700; margin: 0 0 0.45rem; }",
        ".q-id { font-family: ui-monospace, monospace; background: #e2e8f0; padding: 0.1rem 0.4rem; border-radius: 4px; margin-right: 0.4rem; }",
        ".primer { color: #334155; font-size: 0.92rem; white-space: pre-line; margin: 0 0 0.7rem; }",
        ".answer { background: #f1f5f9; border-left: 3px solid #334155; padding: 0.65rem 0.85rem; white-space: pre-line; margin: 0; }",
        ".voice { font-size: 0.78rem; color: #475569; font-weight: 500; margin-left: 0.5rem; }",
        "footer { margin-top: 2.5rem; border-top: 1px solid #cbd5e1; padding-top: 1rem; font-size: 0.82rem; color: #475569; }",
        "</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<h1>Eclipse Phase Character Questionnaire: {html.escape(census.character_name)}</h1>",
        f'<p class="meta">{render_markdown_inline_safe(meta.get("source_credits") or "")}</p>',
        (
            f'<p class="meta">Voice: <strong>{html.escape(census.get_narrative_voice_display())}</strong> '
            f"&middot; Progress: <strong>{stats['answered_count']}/{stats['total_questions']} "
            f"({stats['completion_percent']}%)</strong></p>"
        ),
        "</header>",
    ]

    for ch in get_census_chapters(include_appendix=include_appendix):
        qs = get_chapter_questions(
            ch["id"],
            include_sexuality=include_sexuality,
            include_appendix=include_appendix,
            answerable_only=False,
        )
        items: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for q in qs:
            if not q.get("answerable", True):
                if include_unanswered:
                    items.append((q, None))
                continue
            norm = normalize_census_record(responses.get(q["id"]), default_voice=default_voice)
            if norm["answer"].strip():
                items.append((q, norm))
            elif include_unanswered:
                items.append((q, None))
        if not items:
            continue
        parts.append(f"<h2>{html.escape(ch['number'])} &mdash; {html.escape(ch['title'])}</h2>")
        for q, norm in items:
            disp_id = html.escape(str(q.get("display_id") or q["id"]))
            heading = html.escape(str(q["heading"]))
            voice_html = ""
            if norm is not None:
                vlabel = "First-person" if norm["voice"] == "first_person" else "Omniscient"
                voice_html = f'<span class="voice">({html.escape(vlabel)})</span>'
            parts.append('<article class="card">')
            parts.append(f'<p class="q-head"><span class="q-id">{disp_id}</span>{heading}{voice_html}</p>')
            if q.get("primer"):
                parts.append(f'<p class="primer">{html.escape(str(q["primer"]))}</p>')
            if norm is not None:
                parts.append(f'<div class="answer">{html.escape(norm["answer"].strip())}</div>')
            else:
                parts.append('<p class="meta"><em>Unanswered</em></p>')
            parts.append("</article>")

    parts.append("<footer>")
    parts.append(f"<p><strong>Attribution:</strong> {render_markdown_inline_safe(get_census_attribution())}</p>")
    for p in meta.get("legal_notice", []):
        parts.append(f"<p>{html.escape(p)}</p>")
    parts.extend(["</footer>", "</body>", "</html>"])
    return "\n".join(parts)


def export_census_json(census: EclipsePhaseCensus) -> dict[str, Any]:
    meta = get_census_meta()
    stats = compute_census_stats(census)
    responses = census.responses if isinstance(census.responses, dict) else {}
    default_voice = _default_entry_voice_for(census)
    include_sexuality = bool(census.show_sexuality_sections)
    include_appendix = bool(census.show_sensitive_appendix)

    answered_entries = []
    for q in get_all_census_questions(
        include_sexuality=include_sexuality,
        include_appendix=include_appendix,
        answerable_only=True,
    ):
        norm = normalize_census_record(responses.get(q["id"]), default_voice=default_voice)
        if not norm["answer"].strip():
            continue
        answered_entries.append(
            {
                "id": q["id"],
                "display_id": q.get("display_id") or q["id"],
                "chapter_id": q["chapter_id"],
                "heading": q["heading"],
                "answer": norm["answer"],
                "voice": norm["voice"],
                "updated_at": norm["updated_at"],
            }
        )

    return {
        "schema_version": meta["schema_version"],
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "license": meta["license"],
        "attribution_notice": meta["attribution_notice"],
        "character_name": census.character_name,
        "slug": census.slug,
        "narrative_voice": census.narrative_voice,
        "show_sexuality_sections": include_sexuality,
        "show_sensitive_appendix": include_appendix,
        "stats": stats,
        "responses": answered_entries,
    }
