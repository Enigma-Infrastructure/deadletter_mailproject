"""Shared dossier & Discord-linking service layer for web views and Discord bot."""
from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from spacemarches.models import CharacterDossier, DiscordLink
from spacemarches.questionnaire import (
    get_all_questions,
    get_attribution_notice,
    get_question,
)

LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_discord_link_code(user) -> str:
    """Create or refresh a one-time 8-char Discord link code for an authenticated user."""
    if user is None or not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required to generate a Discord link code.")

    with transaction.atomic():
        for _ in range(10):
            candidate = get_random_string(8, allowed_chars=LINK_CODE_ALPHABET)
            if not DiscordLink.objects.filter(link_code=candidate).exists():
                break
        else:
            raise RuntimeError("Unable to allocate a unique Discord link code.")

        link, _created = DiscordLink.objects.update_or_create(
            user=user,
            defaults={"link_code": candidate},
        )
        return link.link_code


def complete_discord_link(code: str, discord_user_id: str) -> DiscordLink:
    """Bind a Discord user ID to the user owning the given one-time link code."""
    normalized_code = (code or "").strip().upper()
    normalized_discord_id = str(discord_user_id or "").strip()

    if not normalized_code:
        raise ValueError("Link code cannot be empty.")
    if not normalized_discord_id:
        raise ValueError("Discord user ID cannot be empty.")

    with transaction.atomic():
        link = DiscordLink.objects.select_for_update().filter(link_code=normalized_code).first()
        if link is None:
            raise ValueError("Invalid or expired Discord link code.")

        conflict = (
            DiscordLink.objects.filter(discord_user_id=normalized_discord_id)
            .exclude(pk=link.pk)
            .exists()
        )
        if conflict:
            raise ValueError("This Discord account is already linked to a different website user.")

        link.discord_user_id = normalized_discord_id
        link.link_code = None
        link.linked_at = timezone.now()
        link.save(update_fields=["discord_user_id", "link_code", "linked_at"])
        return link


def compute_dossier_stats(dossier: CharacterDossier) -> dict[str, Any]:
    responses = dossier.responses if isinstance(dossier.responses, dict) else {}
    private_keys = set(dossier.private_keys or [])

    questions = get_all_questions(include_sensitive=dossier.show_sensitive_appendix)
    core_questions = [q for q in questions if q["tier"] == "core"]
    deep_questions = [q for q in questions if q["tier"] == "deep"]
    sensitive_questions = [q for q in questions if q["tier"] == "sensitive_appendix"]

    def _is_answered(qid: str) -> bool:
        entry = responses.get(qid)
        return isinstance(entry, dict) and bool(str(entry.get("answer", "")).strip())

    core_answered = sum(1 for q in core_questions if _is_answered(q["id"]))
    deep_answered = sum(1 for q in deep_questions if _is_answered(q["id"]))
    sensitive_answered = sum(1 for q in sensitive_questions if _is_answered(q["id"]))
    answered_count = core_answered + deep_answered + sensitive_answered
    total_questions = len(questions)
    completion_percent = round((answered_count / total_questions) * 100) if total_questions else 0

    return {
        "answered_count": answered_count,
        "core_answered": core_answered,
        "core_total": len(core_questions),
        "deep_answered": deep_answered,
        "deep_total": len(deep_questions),
        "sensitive_answered": sensitive_answered,
        "sensitive_total": len(sensitive_questions),
        "total_questions": total_questions,
        "completion_percent": completion_percent,
        "gm_only_count": len(private_keys),
    }


def save_dossier_answer(
    dossier: CharacterDossier,
    question_id: str,
    answer_text: str,
    session_tag: str = "",
    source: str = "web",
    is_gm_only: bool | None = None,
) -> dict[str, Any]:
    """
    Validate question_id, preserve any prior non-empty answer in revisions,
    update private_keys if is_gm_only is explicitly provided, save atomically,
    and return completion stats.
    """
    qid = str(question_id or "").strip()
    if get_question(qid) is None:
        raise ValueError(f"Unknown questionnaire question ID: {qid}")

    normalized_source = (source or "web").strip().lower()
    if normalized_source not in {"web", "discord"}:
        raise ValueError(f"Invalid answer source '{source}'; expected 'web' or 'discord'.")

    new_answer = "" if answer_text is None else str(answer_text)
    normalized_tag = (session_tag or "").strip()

    with transaction.atomic():
        locked = CharacterDossier.objects.select_for_update().get(pk=dossier.pk)
        responses = dict(locked.responses or {})
        existing = responses.get(qid)

        revisions: list[dict[str, Any]] = []
        if isinstance(existing, dict):
            prior_revisions = existing.get("revisions")
            if isinstance(prior_revisions, list):
                revisions = list(prior_revisions)
            prior_answer = str(existing.get("answer", ""))
            if prior_answer.strip() and prior_answer != new_answer:
                revisions.append(
                    {
                        "answer": prior_answer,
                        "updated_at": existing.get("updated_at", ""),
                        "session_tag": existing.get("session_tag", ""),
                        "source": existing.get("source", "web"),
                    }
                )

        now_iso = timezone.now().isoformat()
        responses[qid] = {
            "answer": new_answer,
            "updated_at": now_iso,
            "session_tag": normalized_tag,
            "source": normalized_source,
            "revisions": revisions,
        }

        private_keys = list(locked.private_keys or [])
        if is_gm_only is True and qid not in private_keys:
            private_keys.append(qid)
        elif is_gm_only is False and qid in private_keys:
            private_keys = [k for k in private_keys if k != qid]

        locked.responses = responses
        locked.private_keys = private_keys
        locked.save(update_fields=["responses", "private_keys", "updated_at"])

        # Keep passed instance in sync for callers inspecting attributes right away
        dossier.responses = locked.responses
        dossier.private_keys = locked.private_keys
        dossier.updated_at = locked.updated_at

        stats = compute_dossier_stats(locked)
        stats.update(
            {
                "question_id": qid,
                "is_gm_only": qid in private_keys,
                "revision_count": len(revisions),
                "updated_at": now_iso,
                "session_tag": normalized_tag,
                "source": normalized_source,
            }
        )
        return stats


def export_dossier_markdown(dossier: CharacterDossier, include_private: bool = False) -> str:
    """Render answered dossier prompts grouped by category with CC BY-NC-SA 3.0 attribution."""
    responses = dossier.responses if isinstance(dossier.responses, dict) else {}
    private_keys = set(dossier.private_keys or [])
    questions = get_all_questions(include_sensitive=dossier.show_sensitive_appendix)

    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for question in questions:
        qid = question["id"]
        if not include_private and qid in private_keys:
            continue
        entry = responses.get(qid)
        if not isinstance(entry, dict) or not str(entry.get("answer", "")).strip():
            continue
        category = question["category"]
        grouped.setdefault(category, []).append((question, entry))

    lines = [
        f"# {dossier.character_name}",
        "",
        f"- **Narrative Voice:** {dossier.get_narrative_voice_display()}",
        f"- **Owner:** {dossier.user}",
        f"- **Export Scope:** {'Full Dossier (Including GM Eyes Only)' if include_private else 'Player / Public Dossier'}",
        "",
    ]

    if not grouped:
        lines.append("_No answered dossier prompts available for this export scope._")
        lines.append("")
    else:
        for category, items in grouped.items():
            lines.append(f"## {category}")
            lines.append("")
            for question, entry in items:
                qid = question["id"]
                badge = " `[GM EYES ONLY]`" if (include_private and qid in private_keys) else ""
                tag = entry.get("session_tag")
                tag_text = f" _(Session: {tag})_" if tag else ""
                lines.append(f"### [{qid}] {question['prompt']}{badge}{tag_text}")
                lines.append("")
                lines.append(str(entry["answer"]).strip())
                lines.append("")

    attribution = get_attribution_notice()
    if attribution:
        lines.extend(["---", "", f"_{attribution}_", ""])

    return "\n".join(lines)
