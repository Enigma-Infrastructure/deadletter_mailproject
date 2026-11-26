"""Shared dossier & Discord-linking service layer for web views and Discord bot."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from spacemarches.models import CharacterDossier, DiscordIntakeInvite, DiscordLink
from spacemarches.questionnaire import (
    get_all_questions,
    get_attribution_notice,
    get_question,
    get_question_temporal_defaults,
)

LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

ENTRY_KIND_CHARACTER_CREATION = "character_creation"
ENTRY_KIND_POST_ACTION_REPORT = "post_action_report"
ENTRY_KIND_CHOICES = [
    (ENTRY_KIND_CHARACTER_CREATION, "Character Creation"),
    (ENTRY_KIND_POST_ACTION_REPORT, "Post-Action Report"),
]
ENTRY_KIND_LABELS = dict(ENTRY_KIND_CHOICES)

STARDATE_ERA_AUTO = "auto"
STARDATE_ERA_PRE_FALL = "pre_fall"
STARDATE_ERA_FALL = "fall"
STARDATE_ERA_POST_FALL = "post_fall"
STARDATE_ERA_CHOICES = [
    (STARDATE_ERA_AUTO, "Auto by Prompt (Pre-Fall Origin / Fall / 10.000 AF Now)"),
    (STARDATE_ERA_PRE_FALL, "Pre-Fall"),
    (STARDATE_ERA_FALL, "Fall"),
    (STARDATE_ERA_POST_FALL, "Post-Fall (Sol 0.000–10.000+)"),
]
STARDATE_ERA_LABELS = {
    STARDATE_ERA_PRE_FALL: "Pre-Fall",
    STARDATE_ERA_FALL: "Fall",
    STARDATE_ERA_POST_FALL: "Post-Fall",
}

DEFAULT_SOL_NUMBER = "10.000"
DEFAULT_SOL_DATE = "Sol 10.000"

_VERSION_SUFFIX_RE = re.compile(r"_v\d+$", re.IGNORECASE)
_SOL_PREFIX_RE = re.compile(r"^(?:post[-\s]?fall\s+)?(?:sol[-\s]*)?", re.IGNORECASE)


def normalize_entry_kind(entry_kind: str = "", session_tag: str = "") -> str:
    """Normalize entry kind to 'character_creation' or 'post_action_report'."""
    raw = (entry_kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in ENTRY_KIND_LABELS:
        return raw
    if raw in {"creation", "concept", "baseline", "session_0"}:
        return ENTRY_KIND_CHARACTER_CREATION
    if raw in {"post_action", "aar", "report", "scene", "play", "downtime"}:
        return ENTRY_KIND_POST_ACTION_REPORT

    legacy = (session_tag or "").strip().lower()
    if any(token in legacy for token in ("post", "report", "downtime", "action", "scene")):
        return ENTRY_KIND_POST_ACTION_REPORT
    return ENTRY_KIND_CHARACTER_CREATION


def _parse_post_fall_sol_number(raw_sol: str) -> str:
    """Parse and format a user-submitted Post-Fall Sol-date (0.000 - 10.000+)."""
    cleaned = _VERSION_SUFFIX_RE.sub("", (raw_sol or "").strip()).strip()
    cleaned = _SOL_PREFIX_RE.sub("", cleaned).strip()
    if not cleaned:
        raise ValueError("Post-Fall Sol-date is required (e.g. 0.000 to 10.000+).")

    try:
        dec = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid Post-Fall Sol-date '{raw_sol}'. Enter a numeric Sol value (0.000 - 10.000+)."
        ) from exc

    if not dec.is_finite() or dec < Decimal("0"):
        raise ValueError("Post-Fall Sol-date must be 0.000 or greater (0.000 - 10.000+).")

    # Preserve higher precision if provided, otherwise display 3 decimal places (0.000+)
    exponent = dec.as_tuple().exponent
    places = abs(exponent) if isinstance(exponent, int) and exponent < 0 else 0
    if places <= 3:
        return f"{dec:.3f}"
    return format(dec.normalize(), "f")


def normalize_stardate(
    stardate_era: str = "",
    sol_date: str = "",
    session_tag: str = "",
    *,
    question_id: str = "",
    allow_legacy_fallback: bool = False,
) -> tuple[str, str, str]:
    """
    Resolve (stardate_era, sol_number, canonical_sol_date) for Pre-Fall, Fall, or Post-Fall.

    When stardate_era is 'auto' (or empty alongside empty sol_date/session_tag),
    falls back to the prompt's natural temporal attribution (Pre-Fall for origin
    questions like [4], Fall for Fall-era questions like [6.1g], and nominal
    10.000 AF Post-Fall for present-state questions like [3]).
    """
    raw_era = (stardate_era or "").strip().lower().replace("-", "_").replace(" ", "_")
    raw_sol = (sol_date or "").strip()
    legacy = (session_tag or "").strip()

    if raw_era == STARDATE_ERA_AUTO or (not raw_era and not raw_sol and not legacy):
        if question_id:
            q_defaults = get_question_temporal_defaults(question_id)
            raw_era = q_defaults["default_stardate_era"]
            if raw_era == STARDATE_ERA_POST_FALL:
                raw_sol = q_defaults["default_sol_number"] or DEFAULT_SOL_NUMBER
            else:
                raw_sol = ""
        else:
            raw_era = STARDATE_ERA_POST_FALL
            raw_sol = DEFAULT_SOL_NUMBER

    if not raw_era:
        probe = (raw_sol or legacy).lower()
        stripped_probe = _VERSION_SUFFIX_RE.sub("", probe).strip()
        if stripped_probe in {"pre-fall", "pre_fall", "prefall"}:
            raw_era = STARDATE_ERA_PRE_FALL
        elif stripped_probe == "fall":
            raw_era = STARDATE_ERA_FALL
        else:
            raw_era = STARDATE_ERA_POST_FALL

    if raw_era in {"pre_fall", "prefall"}:
        return STARDATE_ERA_PRE_FALL, "", "Pre-Fall"
    if raw_era == "fall":
        return STARDATE_ERA_FALL, "", "Fall"
    if raw_era not in {"post_fall", "postfall", "sol"}:
        raise ValueError(f"Unknown stardate era '{stardate_era}'. Expected auto, pre_fall, fall, or post_fall.")

    candidate = raw_sol or legacy
    if not candidate:
        return STARDATE_ERA_POST_FALL, DEFAULT_SOL_NUMBER, DEFAULT_SOL_DATE

    try:
        sol_num = _parse_post_fall_sol_number(candidate)
        return STARDATE_ERA_POST_FALL, sol_num, f"Sol {sol_num}"
    except ValueError:
        if allow_legacy_fallback:
            clean_legacy = _VERSION_SUFFIX_RE.sub("", " ".join(candidate.split())).strip() or DEFAULT_SOL_DATE
            return STARDATE_ERA_POST_FALL, "", clean_legacy
        raise


def _normalize_existing_record(record: dict[str, Any]) -> dict[str, Any]:
    """Ensure legacy or current dict entries expose consistent stardate/version fields."""
    stardate_era, sol_number, sol_date = normalize_stardate(
        str(record.get("stardate_era") or ""),
        str(record.get("sol_date") or ""),
        str(record.get("session_tag") or ""),
        allow_legacy_fallback=True,
    )
    entry_kind = normalize_entry_kind(
        str(record.get("entry_kind") or ""),
        str(record.get("session_tag") or ""),
    )
    raw_version = record.get("version")
    try:
        version = max(1, int(raw_version))
    except (TypeError, ValueError):
        version = 1
    version_label = str(record.get("version_label") or f"{sol_date}_v{version}")
    return {
        "answer": str(record.get("answer", "")),
        "updated_at": str(record.get("updated_at", "")),
        "entry_kind": entry_kind,
        "entry_kind_label": ENTRY_KIND_LABELS[entry_kind],
        "stardate_era": stardate_era,
        "stardate_era_label": STARDATE_ERA_LABELS[stardate_era],
        "sol_number": sol_number or str(record.get("sol_number") or ""),
        "sol_date": sol_date,
        "version": version,
        "version_label": version_label,
        "session_tag": str(record.get("session_tag") or version_label),
        "source": str(record.get("source") or "web"),
    }


def _next_version_for_sol_date(
    sol_date: str,
    revisions: list[dict[str, Any]],
    current: dict[str, Any] | None = None,
) -> int:
    target = sol_date.casefold()
    max_ver = 0
    for rev in revisions:
        norm = _normalize_existing_record(rev)
        if norm["sol_date"].casefold() == target:
            max_ver = max(max_ver, norm["version"])
    if isinstance(current, dict) and str(current.get("answer", "")).strip():
        norm_cur = _normalize_existing_record(current)
        if norm_cur["sol_date"].casefold() == target:
            max_ver = max(max_ver, norm_cur["version"])
    return max_ver + 1


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


def register_discord_intake_invite(
    target_discord_user_id: str,
    *,
    invited_by_user=None,
) -> DiscordIntakeInvite:
    """Authorize an unlinked Discord user to create & fill character dossiers via intake onboarding."""
    normalized_id = str(target_discord_user_id or "").strip()
    if not normalized_id:
        raise ValueError("Target Discord user ID cannot be empty.")

    with transaction.atomic():
        invite, created = DiscordIntakeInvite.objects.select_for_update().get_or_create(
            discord_user_id=normalized_id,
            defaults={"invited_by": invited_by_user},
        )
        if not created and invited_by_user is not None and invite.invited_by_id != getattr(invited_by_user, "pk", None):
            invite.invited_by = invited_by_user
            invite.save(update_fields=["invited_by", "updated_at"])
        elif not created:
            invite.save(update_fields=["updated_at"])
        return invite


def complete_discord_link(code: str, discord_user_id: str) -> DiscordLink:
    """Bind a Discord user ID to the user owning the given link code and claim unclaimed dossiers."""
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

        invite = (
            DiscordIntakeInvite.objects.select_for_update()
            .filter(discord_user_id=normalized_discord_id)
            .first()
        )
        unclaimed = list(
            CharacterDossier.objects.select_for_update()
            .filter(user__isnull=True, discord_owner_id=normalized_discord_id)
            .order_by("-updated_at")
        )

        claimed_dossiers: list[CharacterDossier] = []
        for dossier in unclaimed:
            base = dossier.slug or "character"
            candidate = base
            counter = 1
            while (
                CharacterDossier.objects.filter(user=link.user, slug=candidate)
                .exclude(pk=dossier.pk)
                .exists()
            ):
                counter += 1
                candidate = f"{base[:140]}-{counter}"
            dossier.user = link.user
            dossier.slug = candidate
            dossier.save(update_fields=["user", "slug"])
            claimed_dossiers.append(dossier)

        link.discord_user_id = normalized_discord_id
        link.link_code = None
        link.linked_at = timezone.now()
        update_fields = ["discord_user_id", "link_code", "linked_at"]

        if link.active_dossier_id is None and claimed_dossiers:
            preferred = None
            if invite is not None and invite.active_dossier_id:
                preferred = next((d for d in claimed_dossiers if d.pk == invite.active_dossier_id), None)
            link.active_dossier = preferred or claimed_dossiers[0]
            update_fields.append("active_dossier")

        link.save(update_fields=update_fields)
        if invite is not None:
            invite.delete()

        link.claimed_dossiers = claimed_dossiers
        return link


def reassign_dossier_control(
    dossier: CharacterDossier,
    *,
    target_user=None,
    discord_owner_id: str | None = None,
) -> CharacterDossier:
    """Reassign website user control and/or Discord owner ID for an existing CharacterDossier."""
    raw_discord = "" if discord_owner_id is None else str(discord_owner_id).strip()

    with transaction.atomic():
        locked = CharacterDossier.objects.select_for_update().get(pk=dossier.pk)
        previous_user_id = locked.user_id

        if target_user is not None:
            resolved_discord_id = raw_discord
            if not resolved_discord_id:
                target_link = DiscordLink.objects.filter(user=target_user).first()
                if target_link is not None and target_link.discord_user_id:
                    resolved_discord_id = target_link.discord_user_id
        else:
            resolved_discord_id = raw_discord

        base = locked.slug or slugify(locked.character_name)[:140] or "character"
        candidate = base
        counter = 1
        if target_user is not None:
            conflict_qs = CharacterDossier.objects.filter(user=target_user)
        elif resolved_discord_id:
            conflict_qs = CharacterDossier.objects.filter(
                user__isnull=True,
                discord_owner_id=resolved_discord_id,
            )
        else:
            conflict_qs = CharacterDossier.objects.filter(user__isnull=True)

        while conflict_qs.filter(slug=candidate).exclude(pk=locked.pk).exists():
            counter += 1
            candidate = f"{base[:140]}-{counter}"

        locked.user = target_user
        locked.discord_owner_id = resolved_discord_id
        locked.slug = candidate
        locked.save(update_fields=["user", "discord_owner_id", "slug", "updated_at"])

        if previous_user_id and previous_user_id != getattr(target_user, "pk", None):
            DiscordLink.objects.filter(user_id=previous_user_id, active_dossier_id=locked.pk).update(
                active_dossier=None
            )

        dossier.user = locked.user
        dossier.user_id = locked.user_id
        dossier.discord_owner_id = locked.discord_owner_id
        dossier.slug = locked.slug
        dossier.updated_at = locked.updated_at
        return locked


def _normalize_narrative_voice(raw_voice: str = "") -> str:
    cleaned = (raw_voice or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"", "first", "first_person", "1st", "agent", "log"}:
        return CharacterDossier.VOICE_FIRST_PERSON
    if cleaned in {"omni", "omniscient", "third", "3rd", "institution", "institutional", "dossier"}:
        return CharacterDossier.VOICE_OMNISCIENT
    if cleaned.upper() in {CharacterDossier.VOICE_FIRST_PERSON, CharacterDossier.VOICE_OMNISCIENT}:
        return cleaned.upper()
    raise ValueError(
        "Unknown narrative voice. Use 'first' (First-person agent log) or 'omniscient' (institutional dossier)."
    )


def _resolve_dossier_from_qs(qs, identifier: str) -> CharacterDossier:
    ident = (identifier or "").strip()
    if not ident:
        raise ValueError("Character name or slug is required.")

    ordered = qs.order_by("-updated_at")
    if ident.isdigit():
        by_pk = ordered.filter(pk=int(ident)).first()
        if by_pk is not None:
            return by_pk

    by_slug = ordered.filter(slug__iexact=ident).first()
    if by_slug is not None:
        return by_slug

    by_name = ordered.filter(character_name__iexact=ident).first()
    if by_name is not None:
        return by_name

    partial = list(ordered.filter(character_name__icontains=ident)[:5])
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = ", ".join(d.character_name for d in partial)
        raise ValueError(f"Multiple characters match '{ident}': {names}. Be more specific.")

    raise ValueError(f"No Character Dossier matching '{ident}' found.")


def _resolve_user_dossier(user, identifier: str) -> CharacterDossier:
    return _resolve_dossier_from_qs(CharacterDossier.objects.filter(user=user), identifier)


def get_discord_actor_context(
    discord_user_id: str,
) -> tuple[DiscordLink | None, DiscordIntakeInvite | None, list[CharacterDossier]]:
    normalized_id = str(discord_user_id or "").strip()
    link = (
        DiscordLink.objects.select_related("user", "active_dossier")
        .filter(discord_user_id=normalized_id)
        .first()
    )
    if link is not None:
        dossiers = list(CharacterDossier.objects.filter(user=link.user).order_by("-updated_at"))
        return link, None, dossiers

    invite = (
        DiscordIntakeInvite.objects.select_related("invited_by", "active_dossier")
        .filter(discord_user_id=normalized_id)
        .first()
    )
    dossiers = list(
        CharacterDossier.objects.filter(user__isnull=True, discord_owner_id=normalized_id)
        .order_by("-updated_at")
    )
    return None, invite, dossiers


def get_user_dossiers_for_discord(
    discord_user_id: str,
) -> tuple[DiscordLink | None, list[CharacterDossier]]:
    link, _invite, dossiers = get_discord_actor_context(discord_user_id)
    return link, dossiers


def resolve_discord_dossier(
    discord_user_id: str,
    character_identifier: str = "",
    *,
    activate: bool = False,
    allow_unlinked: bool = False,
) -> tuple[CharacterDossier | None, dict[str, Any] | None]:
    """Return active or requested CharacterDossier and metadata for a linked or invited Discord user."""
    normalized_id = str(discord_user_id or "").strip()
    link, invite, dossiers = get_discord_actor_context(normalized_id)
    if link is None and invite is None and not dossiers and not allow_unlinked:
        return None, None

    owner_label = str(link.user) if link is not None else f"Discord:{normalized_id}"

    if not dossiers:
        if (character_identifier or "").strip():
            raise ValueError("You have no Character Dossiers yet. Run /dossier create first.")
        return None, {
            "linked": link is not None,
            "invited": invite is not None,
            "username": owner_label,
            "dossiers": [],
        }

    chosen: CharacterDossier | None = None
    if link is not None:
        if (character_identifier or "").strip():
            chosen = _resolve_user_dossier(link.user, character_identifier)
            if activate and link.active_dossier_id != chosen.pk:
                link.active_dossier = chosen
                link.save(update_fields=["active_dossier"])
        elif link.active_dossier is not None and link.active_dossier.user_id == link.user_id:
            chosen = link.active_dossier
        else:
            chosen = dossiers[0]
            if link.active_dossier_id != chosen.pk:
                link.active_dossier = chosen
                link.save(update_fields=["active_dossier"])
    else:
        unclaimed_qs = CharacterDossier.objects.filter(user__isnull=True, discord_owner_id=normalized_id)
        if (character_identifier or "").strip():
            chosen = _resolve_dossier_from_qs(unclaimed_qs, character_identifier)
            if activate:
                inv = invite or register_discord_intake_invite(normalized_id)
                if inv.active_dossier_id != chosen.pk:
                    inv.active_dossier = chosen
                    inv.save(update_fields=["active_dossier", "updated_at"])
        elif (
            invite is not None
            and invite.active_dossier is not None
            and invite.active_dossier.user_id is None
            and invite.active_dossier.discord_owner_id == normalized_id
        ):
            chosen = invite.active_dossier
        else:
            chosen = dossiers[0]
            if invite is not None and invite.active_dossier_id != chosen.pk:
                invite.active_dossier = chosen
                invite.save(update_fields=["active_dossier", "updated_at"])

    stats = compute_dossier_stats(chosen)
    return chosen, {
        "linked": link is not None,
        "invited": invite is not None,
        "username": owner_label,
        "active_dossier_id": chosen.pk,
        "dossiers": dossiers,
        "stats": stats,
    }


def set_active_discord_dossier(discord_user_id: str, character_identifier: str) -> CharacterDossier:
    """Switch the linked or invited Discord user's active CharacterDossier."""
    normalized_id = str(discord_user_id or "").strip()
    link, invite, dossiers = get_discord_actor_context(normalized_id)
    if link is None and invite is None and not dossiers:
        raise ValueError(
            "Your Discord account is not linked yet. Ask a Storyteller to prompt `/intake`, "
            "or generate a link code and run `/link <code>`."
        )

    if link is not None:
        dossier = _resolve_user_dossier(link.user, character_identifier)
        if link.active_dossier_id != dossier.pk:
            link.active_dossier = dossier
            link.save(update_fields=["active_dossier"])
        return dossier

    unclaimed_qs = CharacterDossier.objects.filter(user__isnull=True, discord_owner_id=normalized_id)
    dossier = _resolve_dossier_from_qs(unclaimed_qs, character_identifier)
    inv = invite or register_discord_intake_invite(normalized_id)
    if inv.active_dossier_id != dossier.pk:
        inv.active_dossier = dossier
        inv.save(update_fields=["active_dossier", "updated_at"])
    return dossier


def create_character_dossier_for_discord(
    discord_user_id: str,
    character_name: str,
    narrative_voice: str = "",
    *,
    allow_unlinked: bool = False,
    invited_by_user=None,
) -> CharacterDossier:
    """Create a new CharacterDossier for a linked or invited Discord user and make it active."""
    normalized_id = str(discord_user_id or "").strip()
    clean_name = (character_name or "").strip()
    if not clean_name:
        raise ValueError("Character Name / Callsign cannot be empty.")

    voice = _normalize_narrative_voice(narrative_voice)

    with transaction.atomic():
        link = (
            DiscordLink.objects.select_for_update()
            .select_related("user")
            .filter(discord_user_id=normalized_id)
            .first()
        )
        if link is not None:
            dossier = CharacterDossier.objects.create(
                user=link.user,
                discord_owner_id=normalized_id,
                invited_by=invited_by_user,
                character_name=clean_name[:160],
                narrative_voice=voice,
            )
            link.active_dossier = dossier
            link.save(update_fields=["active_dossier"])
            return dossier

        invite = (
            DiscordIntakeInvite.objects.select_for_update()
            .select_related("invited_by")
            .filter(discord_user_id=normalized_id)
            .first()
        )
        has_existing_unclaimed = CharacterDossier.objects.filter(
            user__isnull=True,
            discord_owner_id=normalized_id,
        ).exists()

        if invite is None and not has_existing_unclaimed and not allow_unlinked:
            raise ValueError(
                "Your Discord account is not linked yet. Ask a Storyteller to prompt `/intake`, "
                "or generate a link code and run `/link <code>`."
            )

        effective_inviter = invited_by_user or (invite.invited_by if invite is not None else None)
        dossier = CharacterDossier.objects.create(
            user=None,
            discord_owner_id=normalized_id,
            invited_by=effective_inviter,
            character_name=clean_name[:160],
            narrative_voice=voice,
        )
        if invite is None:
            invite = DiscordIntakeInvite.objects.create(
                discord_user_id=normalized_id,
                invited_by=effective_inviter,
                active_dossier=dossier,
            )
        else:
            if invited_by_user is not None and invite.invited_by_id is None:
                invite.invited_by = invited_by_user
            invite.active_dossier = dossier
            invite.save(update_fields=["invited_by", "active_dossier", "updated_at"])
        return dossier


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

    visible_ids = {q["id"] for q in questions}
    gm_only_visible_count = len(private_keys & visible_ids)

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
        "gm_only_count": gm_only_visible_count,
    }


def get_dossier_progression_summary(dossier: CharacterDossier) -> dict[str, Any]:
    """Summarize all recorded stardates/Sol-dates and date_v(x) entries across a dossier."""
    responses = dossier.responses if isinstance(dossier.responses, dict) else {}
    private_keys = set(dossier.private_keys or [])
    questions_by_id = {
        q["id"]: q for q in get_all_questions(include_sensitive=dossier.show_sensitive_appendix)
    }

    post_fall_sol_numbers: list[str] = [DEFAULT_SOL_NUMBER]
    seen_sol_numbers: set[str] = {DEFAULT_SOL_NUMBER}
    timeline: list[dict[str, Any]] = []

    def _register_sol_number(sol_num: str) -> None:
        if sol_num and sol_num not in seen_sol_numbers:
            seen_sol_numbers.add(sol_num)
            post_fall_sol_numbers.append(sol_num)

    for qid, raw_entry in responses.items():
        if qid not in questions_by_id or not isinstance(raw_entry, dict):
            continue
        question = questions_by_id[qid]
        raw_revisions = raw_entry.get("revisions")
        if isinstance(raw_revisions, list):
            for rev in raw_revisions:
                if not isinstance(rev, dict) or not str(rev.get("answer", "")).strip():
                    continue
                norm = _normalize_existing_record(rev)
                if norm["stardate_era"] == STARDATE_ERA_POST_FALL:
                    _register_sol_number(norm["sol_number"])
                timeline.append(
                    {
                        "question_id": qid,
                        "prompt": question["prompt"],
                        "is_current": False,
                        "is_gm_only": qid in private_keys,
                        **norm,
                    }
                )

        if str(raw_entry.get("answer", "")).strip():
            norm_cur = _normalize_existing_record(raw_entry)
            if norm_cur["stardate_era"] == STARDATE_ERA_POST_FALL:
                _register_sol_number(norm_cur["sol_number"])
            timeline.append(
                {
                    "question_id": qid,
                    "prompt": question["prompt"],
                    "is_current": True,
                    "is_gm_only": qid in private_keys,
                    **norm_cur,
                }
            )

    timeline.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    latest = timeline[0] if timeline else None

    return {
        "post_fall_sol_numbers": post_fall_sol_numbers,
        "latest_era": latest["stardate_era"] if latest else STARDATE_ERA_AUTO,
        "latest_sol_number": (
            latest["sol_number"]
            if latest and latest["sol_number"]
            else DEFAULT_SOL_NUMBER
        ),
        "latest_sol_date": latest["sol_date"] if latest else DEFAULT_SOL_DATE,
        "timeline": timeline,
        "total_versions": len(timeline),
    }


def save_dossier_answer(
    dossier: CharacterDossier,
    question_id: str,
    answer_text: str = "",
    session_tag: str = "",
    source: str = "web",
    is_gm_only: bool | None = None,
    *,
    entry_kind: str = "",
    stardate_era: str = "",
    sol_date: str = "",
    privacy_only: bool = False,
    propagate: bool = True,
) -> dict[str, Any]:
    """
    Append-only progression saver for a CharacterDossier prompt.

    - Supports 'Pre-Fall', 'Fall', and 'Post-Fall' (with user-submitted Sol-date 0.000 - 10.000+).
    - Never overwrites or deletes existing non-empty responses: prior entries are
      archived into `revisions` and every new/clarified entry receives an
      incremented `date_v(x)` label (`version_label`) and becomes the
      current default displayed over the previous default.
    - Supports `privacy_only=True` to toggle `GM Eyes Only` redaction without
      altering existing answer text or generating a duplicate revision.
    """
    qid = str(question_id or "").strip()
    if get_question(qid) is None:
        raise ValueError(f"Unknown questionnaire question ID: {qid}")

    normalized_source = (source or "web").strip().lower()
    if normalized_source not in {"web", "discord", "census_sync"}:
        raise ValueError(f"Invalid answer source '{source}'; expected 'web', 'discord', or 'census_sync'.")

    new_answer = "" if answer_text is None else str(answer_text)
    normalized_kind = normalize_entry_kind(entry_kind, session_tag=session_tag)

    with transaction.atomic():
        locked = CharacterDossier.objects.select_for_update().get(pk=dossier.pk)
        responses = dict(locked.responses or {})
        existing = responses.get(qid)

        private_keys = list(locked.private_keys or [])
        if is_gm_only is True and qid not in private_keys:
            private_keys.append(qid)
        elif is_gm_only is False and qid in private_keys:
            private_keys = [k for k in private_keys if k != qid]

        if privacy_only:
            locked.private_keys = private_keys
            locked.save(update_fields=["private_keys", "updated_at"])
            dossier.private_keys = locked.private_keys
            dossier.updated_at = locked.updated_at

            cur_norm = (
                _normalize_existing_record(existing)
                if isinstance(existing, dict) and str(existing.get("answer", "")).strip()
                else None
            )
            q_defaults = get_question_temporal_defaults(qid)
            stats = compute_dossier_stats(locked)
            stats.update(
                {
                    "question_id": qid,
                    "is_gm_only": qid in private_keys,
                    "revision_count": len(existing.get("revisions", [])) if isinstance(existing, dict) else 0,
                    "updated_at": cur_norm["updated_at"] if cur_norm else "",
                    "entry_kind": cur_norm["entry_kind"] if cur_norm else normalized_kind,
                    "entry_kind_label": cur_norm["entry_kind_label"] if cur_norm else ENTRY_KIND_LABELS[normalized_kind],
                    "stardate_era": cur_norm["stardate_era"] if cur_norm else q_defaults["default_stardate_era"],
                    "stardate_era_label": (
                        cur_norm["stardate_era_label"]
                        if cur_norm
                        else STARDATE_ERA_LABELS[q_defaults["default_stardate_era"]]
                    ),
                    "sol_number": cur_norm["sol_number"] if cur_norm else q_defaults["default_sol_number"],
                    "sol_date": (
                        cur_norm["sol_date"]
                        if cur_norm
                        else (f"Sol {q_defaults['default_sol_number']}" if q_defaults["default_sol_number"] else STARDATE_ERA_LABELS[q_defaults["default_stardate_era"]])
                    ),
                    "version": cur_norm["version"] if cur_norm else 0,
                    "version_label": cur_norm["version_label"] if cur_norm else "",
                    "session_tag": cur_norm["version_label"] if cur_norm else "",
                    "source": cur_norm["source"] if cur_norm else normalized_source,
                }
            )
            return stats

        normalized_era, normalized_sol_number, normalized_sol = normalize_stardate(
            stardate_era,
            sol_date,
            session_tag=session_tag,
            question_id=qid,
        )

        existing_has_answer = isinstance(existing, dict) and bool(str(existing.get("answer", "")).strip())
        if not new_answer.strip():
            if existing_has_answer:
                raise ValueError(
                    "Existing progression entries cannot be deleted or blanked out; "
                    "add an updated or clarified response instead."
                )
            locked.private_keys = private_keys
            locked.save(update_fields=["private_keys", "updated_at"])
            dossier.private_keys = locked.private_keys
            dossier.updated_at = locked.updated_at
            stats = compute_dossier_stats(locked)
            stats.update(
                {
                    "question_id": qid,
                    "is_gm_only": qid in private_keys,
                    "revision_count": 0,
                    "updated_at": "",
                    "entry_kind": normalized_kind,
                    "entry_kind_label": ENTRY_KIND_LABELS[normalized_kind],
                    "stardate_era": normalized_era,
                    "stardate_era_label": STARDATE_ERA_LABELS[normalized_era],
                    "sol_number": normalized_sol_number,
                    "sol_date": normalized_sol,
                    "version": 0,
                    "version_label": "",
                    "session_tag": "",
                    "source": normalized_source,
                }
            )
            return stats

        revisions: list[dict[str, Any]] = []
        if isinstance(existing, dict) and isinstance(existing.get("revisions"), list):
            revisions = [
                _normalize_existing_record(rev)
                for rev in existing["revisions"]
                if isinstance(rev, dict) and str(rev.get("answer", "")).strip()
            ]

        now_iso = timezone.now().isoformat()

        if existing_has_answer:
            cur_norm = _normalize_existing_record(existing)
            is_identical_content = (
                cur_norm["answer"] == new_answer
                and cur_norm["sol_date"].casefold() == normalized_sol.casefold()
                and cur_norm["stardate_era"] == normalized_era
                and cur_norm["entry_kind"] == normalized_kind
            )
            if is_identical_content:
                locked.private_keys = private_keys
                locked.save(update_fields=["private_keys", "updated_at"])
                dossier.private_keys = locked.private_keys
                dossier.updated_at = locked.updated_at
                stats = compute_dossier_stats(locked)
                stats.update(
                    {
                        "question_id": qid,
                        "is_gm_only": qid in private_keys,
                        "revision_count": len(revisions),
                        "updated_at": cur_norm["updated_at"],
                        "entry_kind": cur_norm["entry_kind"],
                        "entry_kind_label": cur_norm["entry_kind_label"],
                        "stardate_era": cur_norm["stardate_era"],
                        "stardate_era_label": cur_norm["stardate_era_label"],
                        "sol_number": cur_norm["sol_number"],
                        "sol_date": cur_norm["sol_date"],
                        "version": cur_norm["version"],
                        "version_label": cur_norm["version_label"],
                        "session_tag": cur_norm["version_label"],
                        "source": cur_norm["source"],
                        "revisions": list(reversed(revisions)),
                    }
                )
                return stats

            revisions.append(cur_norm)

        next_version = _next_version_for_sol_date(normalized_sol, revisions)
        version_label = f"{normalized_sol}_v{next_version}"

        responses[qid] = {
            "answer": new_answer,
            "updated_at": now_iso,
            "entry_kind": normalized_kind,
            "entry_kind_label": ENTRY_KIND_LABELS[normalized_kind],
            "stardate_era": normalized_era,
            "stardate_era_label": STARDATE_ERA_LABELS[normalized_era],
            "sol_number": normalized_sol_number,
            "sol_date": normalized_sol,
            "version": next_version,
            "version_label": version_label,
            "session_tag": version_label,
            "source": normalized_source,
            "revisions": revisions,
        }

        locked.responses = responses
        locked.private_keys = private_keys
        locked.save(update_fields=["responses", "private_keys", "updated_at"])

        dossier.responses = locked.responses
        dossier.private_keys = locked.private_keys
        dossier.updated_at = locked.updated_at

        synced_census_qid = None
        if propagate and new_answer.strip():
            from spacemarches.services.character_cross_sync import (
                DOSSIER_TO_CENSUS_MAP,
                sync_dossier_answer_to_censuses,
            )

            synced_ids = sync_dossier_answer_to_censuses(
                locked,
                qid,
                new_answer,
                is_gm_only=(qid in private_keys),
            )
            if synced_ids:
                synced_census_qid = DOSSIER_TO_CENSUS_MAP.get(qid)

        stats = compute_dossier_stats(locked)
        stats.update(
            {
                "question_id": qid,
                "is_gm_only": qid in private_keys,
                "revision_count": len(revisions),
                "updated_at": now_iso,
                "entry_kind": normalized_kind,
                "entry_kind_label": ENTRY_KIND_LABELS[normalized_kind],
                "stardate_era": normalized_era,
                "stardate_era_label": STARDATE_ERA_LABELS[normalized_era],
                "sol_number": normalized_sol_number,
                "sol_date": normalized_sol,
                "version": next_version,
                "version_label": version_label,
                "session_tag": version_label,
                "source": normalized_source,
                "synced_census_qid": synced_census_qid,
                "revisions": list(reversed(revisions)),
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
        f"- **Owner:** {dossier.owner_display}",
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
                norm = _normalize_existing_record(entry)
                badge = " `[GM EYES ONLY]`" if (include_private and qid in private_keys) else ""
                tag_text = f" _({norm['entry_kind_label']} · {norm['version_label']})_"
                lines.append(f"### [{qid}] {question['prompt']}{badge}{tag_text}")
                lines.append("")
                lines.append(norm["answer"].strip())
                lines.append("")
                raw_revs = entry.get("revisions") if isinstance(entry.get("revisions"), list) else []
                clean_revs = [
                    _normalize_existing_record(rev)
                    for rev in raw_revs
                    if isinstance(rev, dict) and str(rev.get("answer", "")).strip()
                ]
                if clean_revs:
                    lines.append("**Prior progression history:**")
                    for rev in clean_revs:
                        lines.append(
                            f"- `{rev['version_label']}` ({rev['entry_kind_label']} · {rev['source']}): "
                            f"{rev['answer'].strip()}"
                        )
                    lines.append("")

    attribution = get_attribution_notice()
    if attribution:
        lines.extend(["---", "", f"_{attribution}_", ""])

    return "\n".join(lines)
