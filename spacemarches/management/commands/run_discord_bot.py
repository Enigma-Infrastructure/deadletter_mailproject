"""Django management command running the Spacemarches Discord dossier & intake bot."""
from __future__ import annotations

import inspect
import os
from typing import Any, Literal

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

import discord
from discord import app_commands

from spacemarches.models import CharacterDossier, DiscordIntakeInvite, DiscordLink
from spacemarches.questionnaire import (
    get_all_questions,
    get_categories,
    get_question,
    get_question_temporal_defaults,
)
from spacemarches.services.dossier_service import (
    ENTRY_KIND_CHARACTER_CREATION,
    ENTRY_KIND_POST_ACTION_REPORT,
    complete_discord_link,
    compute_dossier_stats,
    create_character_dossier_for_discord,
    get_discord_actor_context,
    normalize_stardate,
    register_discord_intake_invite,
    resolve_discord_dossier,
    save_dossier_answer,
    set_active_discord_dossier,
)

User = get_user_model()
_ST_ROLE_NAMES = {"st", "storyteller", "gm", "game master", "admin", "moderator"}


# --------------------------------------------------
# Permission & Sync-to-Async DB Helpers
# --------------------------------------------------


def _has_discord_st_permissions(discord_user: Any) -> bool:
    """Return True if a Discord Member holds server admin/manage perms or a Storyteller/GM role."""
    perms = getattr(discord_user, "guild_permissions", None)
    if isinstance(perms, discord.Permissions):
        if perms.administrator or perms.manage_guild:
            return True
    roles = getattr(discord_user, "roles", None)
    if isinstance(roles, (list, tuple)):
        for role in roles:
            name = getattr(role, "name", "")
            if isinstance(name, str) and name.strip().lower() in _ST_ROLE_NAMES:
                return True
    return False


@sync_to_async
def _complete_link_async(code: str, discord_user_id: str) -> tuple[str, str, list[str]]:
    link = complete_discord_link(code=code, discord_user_id=discord_user_id)
    claimed = [d.character_name for d in getattr(link, "claimed_dossiers", [])]
    return str(link.user), link.discord_user_id or "", claimed


@sync_to_async
def _get_link_user_async(discord_user_id: str) -> tuple[bool, int | None, str]:
    link = (
        DiscordLink.objects.select_related("user")
        .filter(discord_user_id=str(discord_user_id or "").strip())
        .first()
    )
    if link is None:
        return False, None, ""
    return True, link.user_id, str(link.user)


@sync_to_async
def _register_intake_invite_async(
    target_discord_user_id: str,
    *,
    invited_by_user_id: int | None = None,
) -> DiscordIntakeInvite:
    invited_by_user = User.objects.filter(pk=invited_by_user_id).first() if invited_by_user_id else None
    return register_discord_intake_invite(
        target_discord_user_id,
        invited_by_user=invited_by_user,
    )


@sync_to_async
def _resolve_dossier_async(
    discord_user_id: str,
    character_identifier: str = "",
    *,
    activate: bool = False,
    allow_unlinked: bool = False,
) -> tuple[CharacterDossier | None, dict[str, Any] | None]:
    return resolve_discord_dossier(
        discord_user_id,
        character_identifier=character_identifier,
        activate=activate,
        allow_unlinked=allow_unlinked,
    )


@sync_to_async
def _get_actor_dossiers_async(discord_user_id: str) -> tuple[bool, bool, list[dict[str, Any]]]:
    """Return (is_authorized, is_linked, dossier_items) for linked or ST-invited Discord users."""
    link, invite, dossiers = get_discord_actor_context(discord_user_id)
    is_linked = link is not None
    is_authorized = is_linked or (invite is not None) or bool(dossiers)
    if not is_authorized:
        return False, False, []

    active_id = None
    if link is not None:
        active_id = link.active_dossier_id
    elif invite is not None:
        active_id = invite.active_dossier_id
    if active_id is None and dossiers:
        active_id = dossiers[0].pk

    items = [
        {
            "dossier": d,
            "stats": compute_dossier_stats(d),
            "is_active": d.pk == active_id,
        }
        for d in dossiers
    ]
    return True, is_linked, items


@sync_to_async
def _swap_active_dossier_async(discord_user_id: str, character_identifier: str) -> tuple[CharacterDossier, dict[str, Any]]:
    dossier = set_active_discord_dossier(discord_user_id, character_identifier)
    stats = compute_dossier_stats(dossier)
    return dossier, stats


@sync_to_async
def _create_dossier_async(
    discord_user_id: str,
    character_name: str,
    narrative_voice: str = "",
    *,
    allow_unlinked: bool = False,
    invited_by_user_id: int | None = None,
) -> tuple[CharacterDossier, dict[str, Any]]:
    invited_by_user = User.objects.filter(pk=invited_by_user_id).first() if invited_by_user_id else None
    dossier = create_character_dossier_for_discord(
        discord_user_id,
        character_name=character_name,
        narrative_voice=narrative_voice,
        allow_unlinked=allow_unlinked,
        invited_by_user=invited_by_user,
    )
    stats = compute_dossier_stats(dossier)
    return dossier, stats


@sync_to_async
def _get_dossier_by_id_async(dossier_id: int) -> CharacterDossier:
    return CharacterDossier.objects.get(pk=dossier_id)


@sync_to_async
def _save_dossier_answer_async(
    dossier_id: int,
    question_id: str,
    answer_text: str,
    session_tag: str = "",
    entry_kind: str = "",
    stardate_era: str = "",
    sol_date: str = "",
) -> dict[str, Any]:
    dossier = CharacterDossier.objects.get(pk=dossier_id)
    return save_dossier_answer(
        dossier=dossier,
        question_id=question_id,
        answer_text=answer_text,
        session_tag=session_tag,
        source="discord",
        entry_kind=entry_kind,
        stardate_era=stardate_era,
        sol_date=sol_date,
    )


async def _check_allowed_actor(interaction: discord.Interaction, allowed_user_id: str | None) -> bool:
    if allowed_user_id and str(interaction.user.id) != str(allowed_user_id):
        await interaction.response.send_message(
            "This intake prompt belongs to another player. Ask a Storyteller to run "
            "`/intake member:@you` or run `/intake` yourself.",
            ephemeral=True,
        )
        return False
    return True


# --------------------------------------------------
# Shared Embed & Intake Builders
# --------------------------------------------------


def _filter_intake_questions(
    dossier: CharacterDossier,
    *,
    scope: str = "core",
    category: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    questions = get_all_questions(include_sensitive=dossier.show_sensitive_appendix)
    responses = dossier.responses if isinstance(dossier.responses, dict) else {}

    normalized_scope = (scope or "").strip().lower()
    if normalized_scope not in {"core", "all", "unanswered"}:
        normalized_scope = "all" if category else "core"

    if category:
        cat_lower = category.strip().lower()
        filtered = [q for q in questions if cat_lower in q.get("category", "").lower()]
        if filtered:
            questions = filtered

    if normalized_scope == "core":
        questions = [q for q in questions if q.get("tier") == "core"]
    elif normalized_scope == "unanswered":
        questions = [
            q
            for q in questions
            if not (
                isinstance(responses.get(q["id"]), dict)
                and bool(str(responses[q["id"]].get("answer", "")).strip())
            )
        ]

    return questions, normalized_scope


def _build_intake_overview_embed(
    dossier: CharacterDossier,
    stats: dict[str, Any],
    *,
    scope: str = "core",
    category: str | None = None,
    shown_count: int = 0,
) -> discord.Embed:
    scope_labels = {
        "core": "Core Prompts",
        "all": "All Prompts",
        "unanswered": "Unanswered Prompts",
    }
    control_note = ""
    if dossier.user_id is None:
        control_note = "\nStatus: **Unclaimed Onboarding Sheet** *(run `/link <code>` later to claim on web)*"
    embed = discord.Embed(
        title=f"Intake: {dossier.character_name}"[:256],
        description=(
            f"Voice: **{dossier.get_narrative_voice_display()}**\n"
            f"Core: **{stats['core_answered']}/{stats['core_total']}** | "
            f"Total: **{stats['answered_count']}/{stats['total_questions']}** "
            f"({stats['completion_percent']}%)\n"
            f"Filter: **{scope_labels.get(scope, 'Core Prompts')}**"
            + (f" · Category: `{category}`" if category else "")
            + control_note
        ),
        color=discord.Color.blue(),
    )
    if shown_count > 25:
        embed.set_footer(text=f"Showing first 25 of {shown_count} matching prompts · Filter by category to narrow")
    else:
        embed.set_footer(text="Select a prompt below to read it in full before editing.")
    return embed


def _build_dossier_overview_embed(
    dossier: CharacterDossier,
    stats: dict[str, Any],
    *,
    total_characters: int = 1,
) -> discord.Embed:
    ownership_line = (
        "Control: **Linked Website Account**\n"
        if dossier.user_id is not None
        else "Control: **Unclaimed Discord Onboarding** *(use `/link <code>` later to claim on web)*\n"
    )
    embed = discord.Embed(
        title=f"Active Dossier: {dossier.character_name}"[:256],
        description=(
            f"Slug: `{dossier.slug}`\n"
            f"{ownership_line}"
            f"Narrative Voice: **{dossier.get_narrative_voice_display()}**\n"
            f"Core Prompts: **{stats['core_answered']}/{stats['core_total']}**\n"
            f"Deep Prompts: **{stats['deep_answered']}/{stats['deep_total']}**\n"
            f"Total Completion: **{stats['answered_count']}/{stats['total_questions']}** "
            f"({stats['completion_percent']}%)"
        ),
        color=discord.Color.teal(),
    )
    embed.set_footer(
        text=(
            f"{total_characters} character(s) · "
            "Use the buttons below to start /intake, create a character, or swap active dossiers."
        )[:2048]
    )
    return embed


def _build_question_detail_embed(dossier: CharacterDossier, question: dict[str, Any]) -> discord.Embed:
    """Render the full, unclipped question prompt, lore note, and current answer."""
    qid = question["id"]
    category = question.get("category") or "Dossier Prompt"

    desc_parts = [f"**{question['prompt']}**"]
    lore = (question.get("lore_text") or "").strip()
    if lore:
        desc_parts.append(f"*{lore}*")

    embed = discord.Embed(
        title=f"[{qid}] {category}"[:256],
        description="\n\n".join(desc_parts)[:4096],
        color=discord.Color.blue(),
    )

    responses = dossier.responses if isinstance(dossier.responses, dict) else {}
    existing = responses.get(qid)
    if isinstance(existing, dict) and str(existing.get("answer", "")).strip():
        ver = existing.get("version_label") or existing.get("sol_date") or "Saved"
        answer_text = str(existing.get("answer", "")).strip()
        if len(answer_text) > 1000:
            answer_text = answer_text[:997] + "..."
        embed.add_field(name=f"Current Response ({ver})", value=answer_text, inline=False)
    else:
        era = str(question.get("default_stardate_era") or "post_fall")
        sol_num = str(question.get("default_sol_number") or "10.000")
        default_era = (
            f"Sol {sol_num}"
            if era == "post_fall"
            else ("Fall" if era == "fall" else "Pre-Fall")
        )
        embed.add_field(
            name="Status",
            value=f"Unanswered · Default Stardate: **{default_era}**",
            inline=False,
        )

    scope = str(question.get("temporal_scope") or "").strip()
    footer_parts = [dossier.character_name]
    if scope:
        footer_parts.append(scope.replace("_", " ").title())
    footer_parts.append("Click Answer / Edit below")
    embed.set_footer(text=" · ".join(footer_parts)[:2048])
    return embed


# --------------------------------------------------
# Discord UI Components (Modals, Selects, Archive & Debrief Views)
# --------------------------------------------------


class SendTargetIntakeButton(discord.ui.Button):
    """One-click follow-up button letting an ST/linked creator send the new character's intake prompt."""

    def __init__(
        self,
        *,
        target_member: discord.Member | discord.User,
        dossier: CharacterDossier,
        inviter_label: str,
        row: int = 0,
    ):
        super().__init__(
            label=f"Send Intake to {target_member.display_name}"[:80],
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self.target_member = target_member
        self.dossier = dossier
        self.inviter_label = inviter_label

    async def callback(self, interaction: discord.Interaction) -> None:
        fresh = await _get_dossier_by_id_async(self.dossier.pk)
        stats = compute_dossier_stats(fresh)
        questions, resolved_scope = _filter_intake_questions(fresh, scope="core")
        embed = _build_intake_overview_embed(
            fresh,
            stats,
            scope=resolved_scope,
            shown_count=len(questions),
        )
        target_id = str(self.target_member.id)
        view = DossierSelectView(
            dossier=fresh,
            questions=questions,
            allowed_user_id=target_id,
        )
        mention = getattr(self.target_member, "mention", f"<@{target_id}>")
        channel = getattr(interaction, "channel", None)
        channel_send = getattr(channel, "send", None)
        channel_can_send = channel is not None and inspect.iscoroutinefunction(channel_send)
        try:
            await self.target_member.send(embed=embed, view=view)
        except discord.Forbidden:
            if channel_can_send:
                await channel.send(
                    content=(
                        f"{mention} — **{self.inviter_label}** opened your Spacemarches character intake "
                        "(posted here because your DMs are closed):"
                    ),
                    embed=embed,
                    view=view,
                )
                await interaction.response.send_message(
                    f"Could not DM **{self.target_member.display_name}**; posted intake for **{fresh.character_name}** in this channel instead.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                f"Could not DM {self.target_member.display_name}; run `/intake member:@player delivery:channel` instead.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Sent intake prompt for **{fresh.character_name}** to **{self.target_member.display_name}** via DM.",
            ephemeral=True,
        )


class CreateDossierModal(discord.ui.Modal, title="Initialize Character Dossier"):
    """Modal creating a new CharacterDossier and setting it active (linked, ST-invited, or ST-for-member)."""

    def __init__(
        self,
        *,
        allow_unlinked: bool = False,
        invited_by_user_id: int | None = None,
        start_intake_on_create: bool = False,
        scope: str = "core",
        category: str | None = None,
        target_discord_user_id: str | None = None,
        target_display_name: str = "",
        target_member: discord.Member | discord.User | None = None,
    ):
        super().__init__()
        self.allow_unlinked = allow_unlinked
        self.invited_by_user_id = invited_by_user_id
        self.start_intake_on_create = start_intake_on_create
        self.scope = scope or "core"
        self.category = category
        self.target_discord_user_id = str(target_discord_user_id) if target_discord_user_id else None
        self.target_display_name = target_display_name
        self.target_member = target_member

        self.character_name_input = discord.ui.TextInput(
            label="Character Name / Callsign",
            style=discord.TextStyle.short,
            required=True,
            max_length=160,
            placeholder="e.g. Dr. Elena Vance // 'Specter'",
        )
        self.add_item(self.character_name_input)

        self.narrative_voice_input = discord.ui.TextInput(
            label="Narrative Voice (first or omniscient)",
            style=discord.TextStyle.short,
            default="first",
            required=False,
            max_length=32,
            placeholder="first (agent log) or omniscient (institutional tone)",
        )
        self.add_item(self.narrative_voice_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        owner_discord_id = self.target_discord_user_id or str(interaction.user.id)
        creating_for_other = owner_discord_id != str(interaction.user.id)
        try:
            dossier, stats = await _create_dossier_async(
                owner_discord_id,
                character_name=self.character_name_input.value,
                narrative_voice=self.narrative_voice_input.value,
                allow_unlinked=self.allow_unlinked,
                invited_by_user_id=self.invited_by_user_id,
            )
        except ValueError as err:
            await interaction.response.send_message(f"Could not create dossier: {err}", ephemeral=True)
            return

        if creating_for_other:
            target_label = self.target_display_name or f"Discord:{owner_discord_id}"
            embed = _build_dossier_overview_embed(dossier, stats, total_characters=1)
            embed.title = f"Initialized for {target_label}: {dossier.character_name}"[:256]
            embed.set_footer(
                text=(
                    f"Assigned to {target_label} · Click below or run `/intake member:` to send prompts."
                )[:2048]
            )
            if self.target_member is not None:
                view: discord.ui.View | None = discord.ui.View(timeout=300)
                view.add_item(
                    SendTargetIntakeButton(
                        target_member=self.target_member,
                        dossier=dossier,
                        inviter_label=getattr(interaction.user, "display_name", "Storyteller"),
                    )
                )
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if self.start_intake_on_create:
            questions, resolved_scope = _filter_intake_questions(
                dossier,
                scope=self.scope,
                category=self.category,
            )
            if not questions:
                questions, resolved_scope = _filter_intake_questions(dossier, scope="all")
            embed = _build_intake_overview_embed(
                dossier,
                stats,
                scope=resolved_scope,
                category=self.category,
                shown_count=len(questions),
            )
            embed.title = f"Created & Starting Intake: {dossier.character_name}"[:256]
            view = DossierSelectView(
                dossier=dossier,
                questions=questions,
                allowed_user_id=str(interaction.user.id),
            )
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return

        _auth, _is_linked, items = await _get_actor_dossiers_async(str(interaction.user.id))
        embed = _build_dossier_overview_embed(dossier, stats, total_characters=max(len(items), 1))
        embed.title = f"Initialized & Active: {dossier.character_name}"[:256]
        view = DossierArchiveView(items=items, active_dossier=dossier, allowed_user_id=str(interaction.user.id))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class DossierAnswerModal(discord.ui.Modal):
    """Modal pre-filled with the character's current answer and stardate for a prompt."""

    def __init__(
        self,
        *,
        dossier_id: int,
        question: dict[str, Any],
        current_answer: str = "",
        session_tag: str = "",
        entry_kind: str = "",
        stardate_era: str = "",
        sol_date: str = "",
    ):
        qid = question["id"]
        super().__init__(title=f"Dossier [{qid}]"[:45])
        self.dossier_id = dossier_id
        self.question_id = qid
        self.session_tag = session_tag
        self.entry_kind = entry_kind or (
            ENTRY_KIND_POST_ACTION_REPORT
            if (current_answer or "").strip()
            else ENTRY_KIND_CHARACTER_CREATION
        )
        self.stardate_era = stardate_era

        q_defaults = get_question_temporal_defaults(qid)
        fallback_stardate = (
            q_defaults["default_sol_number"]
            if q_defaults["default_stardate_era"] == "post_fall"
            else ("Fall" if q_defaults["default_stardate_era"] == "fall" else "Pre-Fall")
        )
        default_stardate = (sol_date or session_tag or fallback_stardate).strip()[:60]
        self.stardate_input = discord.ui.TextInput(
            label="Stardate (Pre-Fall, Fall, or Sol 0.000+)",
            style=discord.TextStyle.short,
            default=default_stardate,
            required=True,
            max_length=60,
            placeholder="Pre-Fall, Fall, or 10.000",
        )
        self.add_item(self.stardate_input)

        prompt_label = question["prompt"]
        if len(prompt_label) > 45:
            prompt_label = f"Response for [{qid}]"

        self.answer_input = discord.ui.TextInput(
            label=prompt_label,
            style=discord.TextStyle.paragraph,
            default=(current_answer or "")[:4000],
            required=False,
            max_length=4000,
            placeholder=question["prompt"][:100] if len(question["prompt"]) > 45 else f"Response for [{qid}]...",
        )
        self.add_item(self.answer_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_stardate = (self.stardate_input.value or "").strip()
        try:
            stats = await _save_dossier_answer_async(
                dossier_id=self.dossier_id,
                question_id=self.question_id,
                answer_text=self.answer_input.value,
                session_tag=self.session_tag,
                entry_kind=self.entry_kind,
                stardate_era="",
                sol_date=raw_stardate,
            )
        except ValueError as err:
            await interaction.response.send_message(f"Could not save [{self.question_id}]: {err}", ephemeral=True)
            return

        ver_note = f" ({stats['entry_kind_label']} · {stats['version_label']})" if stats.get("version_label") else ""
        await interaction.response.send_message(
            f"Saved **[{self.question_id}]**{ver_note}. Progress: "
            f"{stats['answered_count']}/{stats['total_questions']} ({stats['completion_percent']}%).",
            ephemeral=True,
        )


class LaunchIntakeButton(discord.ui.Button):
    """Transitions from a dossier overview directly into the /intake questionnaire."""

    def __init__(
        self,
        *,
        dossier: CharacterDossier,
        scope: str = "core",
        category: str | None = None,
        allowed_user_id: str | None = None,
        row: int = 0,
    ):
        super().__init__(
            label="Start / Continue Intake",
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self.dossier = dossier
        self.scope = scope
        self.category = category
        self.allowed_user_id = allowed_user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _check_allowed_actor(interaction, self.allowed_user_id):
            return
        fresh_dossier = await _get_dossier_by_id_async(self.dossier.pk)
        stats = compute_dossier_stats(fresh_dossier)
        questions, resolved_scope = _filter_intake_questions(
            fresh_dossier,
            scope=self.scope,
            category=self.category,
        )
        embed = _build_intake_overview_embed(
            fresh_dossier,
            stats,
            scope=resolved_scope,
            category=self.category,
            shown_count=len(questions),
        )
        view = DossierSelectView(
            dossier=fresh_dossier,
            questions=questions,
            allowed_user_id=self.allowed_user_id,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class CreateDossierButton(discord.ui.Button):
    """Opens CreateDossierModal to start a brand-new character narrative."""

    def __init__(
        self,
        *,
        label: str = "+ New Character",
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
        allowed_user_id: str | None = None,
        allow_unlinked: bool = False,
        invited_by_user_id: int | None = None,
        start_intake_on_create: bool = False,
        scope: str = "core",
        category: str | None = None,
        row: int = 0,
    ):
        super().__init__(label=label[:80], style=style, row=row)
        self.allowed_user_id = allowed_user_id
        self.allow_unlinked = allow_unlinked
        self.invited_by_user_id = invited_by_user_id
        self.start_intake_on_create = start_intake_on_create
        self.scope = scope
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _check_allowed_actor(interaction, self.allowed_user_id):
            return
        await interaction.response.send_modal(
            CreateDossierModal(
                allow_unlinked=self.allow_unlinked,
                invited_by_user_id=self.invited_by_user_id,
                start_intake_on_create=self.start_intake_on_create,
                scope=self.scope,
                category=self.category,
            )
        )


class CharacterSelect(discord.ui.Select):
    """Dropdown switching which CharacterDossier is active for the Discord user."""

    def __init__(
        self,
        *,
        items: list[dict[str, Any]],
        allowed_user_id: str | None = None,
        row: int = 1,
    ):
        self.allowed_user_id = allowed_user_id
        options: list[discord.SelectOption] = []
        for entry in items[:25]:
            d = entry["dossier"]
            stats = entry["stats"]
            is_active = bool(entry.get("is_active"))
            marker = "★" if is_active else "○"
            label = f"{marker} {d.character_name}"[:100]
            desc = (
                f"{d.get_narrative_voice_display()} · "
                f"Core {stats['core_answered']}/{stats['core_total']} · "
                f"Total {stats['answered_count']}/{stats['total_questions']}"
            )[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(d.pk),
                    description=desc,
                    default=is_active,
                )
            )

        super().__init__(
            placeholder="Swap active character dossier...",
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _check_allowed_actor(interaction, self.allowed_user_id):
            return
        selected_pk = self.values[0]
        try:
            dossier, stats = await _swap_active_dossier_async(str(interaction.user.id), selected_pk)
        except ValueError as err:
            await interaction.response.send_message(f"Swap failed: {err}", ephemeral=True)
            return

        _auth, _is_linked, items = await _get_actor_dossiers_async(str(interaction.user.id))
        embed = _build_dossier_overview_embed(dossier, stats, total_characters=len(items))
        view = DossierArchiveView(
            items=items,
            active_dossier=dossier,
            allowed_user_id=self.allowed_user_id,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class DossierArchiveView(discord.ui.View):
    """Archive view for /dossier open, /dossier list, and /dossier swap."""

    def __init__(
        self,
        *,
        items: list[dict[str, Any]],
        active_dossier: CharacterDossier | None = None,
        allowed_user_id: str | None = None,
        allow_unlinked: bool = False,
        invited_by_user_id: int | None = None,
        timeout: float = 300,
    ):
        super().__init__(timeout=timeout)
        if active_dossier is not None:
            self.add_item(
                LaunchIntakeButton(
                    dossier=active_dossier,
                    allowed_user_id=allowed_user_id,
                    row=0,
                )
            )
        self.add_item(
            CreateDossierButton(
                allowed_user_id=allowed_user_id,
                allow_unlinked=allow_unlinked,
                invited_by_user_id=invited_by_user_id,
                row=0,
            )
        )
        if items:
            self.add_item(CharacterSelect(items=items, allowed_user_id=allowed_user_id, row=1))


class OnboardingInviteView(discord.ui.View):
    """Onboarding prompt sent to an unlinked player triggered via /intake member:@Player."""

    def __init__(
        self,
        *,
        target_discord_user_id: str,
        invited_by_user_id: int | None = None,
        scope: str = "core",
        category: str | None = None,
        timeout: float = 900,
    ):
        super().__init__(timeout=timeout)
        self.add_item(
            CreateDossierButton(
                label="Create Character & Start Intake",
                style=discord.ButtonStyle.primary,
                allowed_user_id=target_discord_user_id,
                allow_unlinked=True,
                invited_by_user_id=invited_by_user_id,
                start_intake_on_create=True,
                scope=scope,
                category=category,
                row=0,
            )
        )


class DossierEditButton(discord.ui.Button):
    """Opens the answer modal while keeping the unclipped prompt visible above."""

    def __init__(
        self,
        *,
        dossier: CharacterDossier,
        question: dict[str, Any],
        session_tag: str = "",
        allowed_user_id: str | None = None,
        row: int = 0,
    ):
        qid = question["id"]
        super().__init__(
            label=f"Answer / Edit [{qid}]"[:80],
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self.dossier = dossier
        self.question = question
        self.session_tag = session_tag
        self.allowed_user_id = allowed_user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _check_allowed_actor(interaction, self.allowed_user_id):
            return
        fresh_dossier = await _get_dossier_by_id_async(self.dossier.pk)
        qid = self.question["id"]
        responses = fresh_dossier.responses if isinstance(fresh_dossier.responses, dict) else {}
        existing = responses.get(qid)
        current_answer = str(existing.get("answer", "")) if isinstance(existing, dict) else ""
        current_sol = str(existing.get("sol_date", "")) if isinstance(existing, dict) else ""
        current_era = str(existing.get("stardate_era", "")) if isinstance(existing, dict) else ""
        modal = DossierAnswerModal(
            dossier_id=fresh_dossier.pk,
            question=self.question,
            current_answer=current_answer,
            session_tag=self.session_tag,
            stardate_era=current_era,
            sol_date=current_sol,
        )
        await interaction.response.send_modal(modal)


class DossierQuestionSelect(discord.ui.Select):
    """Dropdown selecting a questionnaire prompt to preview in full before editing."""

    def __init__(
        self,
        *,
        dossier: CharacterDossier,
        questions: list[dict[str, Any]],
        session_tag: str = "",
        selected_id: str = "",
        allowed_user_id: str | None = None,
        row: int = 0,
    ):
        self.dossier = dossier
        self.questions = questions
        self.session_tag = session_tag
        self.allowed_user_id = allowed_user_id
        responses = dossier.responses if isinstance(dossier.responses, dict) else {}

        options: list[discord.SelectOption] = []
        for q in questions[:25]:
            qid = q["id"]
            existing = responses.get(qid)
            is_answered = isinstance(existing, dict) and bool(str(existing.get("answer", "")).strip())
            marker = "✓" if is_answered else "○"
            label = f"{marker} [{qid}] {q['prompt']}"[:100]
            desc = (q.get("category") or "")[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=qid,
                    description=desc,
                    default=(qid == selected_id),
                )
            )

        super().__init__(
            placeholder="Choose a dossier question to read or edit...",
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _check_allowed_actor(interaction, self.allowed_user_id):
            return
        qid = self.values[0]
        question = get_question(qid)
        if question is None:
            await interaction.response.send_message(f"Unknown question ID: {qid}", ephemeral=True)
            return
        fresh_dossier = await _get_dossier_by_id_async(self.dossier.pk)
        embed = _build_question_detail_embed(fresh_dossier, question)
        view = DossierSelectView(
            dossier=fresh_dossier,
            questions=self.questions,
            session_tag=self.session_tag,
            selected_question=question,
            allowed_user_id=self.allowed_user_id,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class DossierSelectView(discord.ui.View):
    def __init__(
        self,
        *,
        dossier: CharacterDossier,
        questions: list[dict[str, Any]],
        session_tag: str = "",
        selected_question: dict[str, Any] | None = None,
        allowed_user_id: str | None = None,
        timeout: float = 300,
    ):
        super().__init__(timeout=timeout)
        select_row = 0
        if selected_question is not None:
            self.add_item(
                DossierEditButton(
                    dossier=dossier,
                    question=selected_question,
                    session_tag=session_tag,
                    allowed_user_id=allowed_user_id,
                    row=0,
                )
            )
            select_row = 1
        if questions:
            self.add_item(
                DossierQuestionSelect(
                    dossier=dossier,
                    questions=questions,
                    session_tag=session_tag,
                    selected_id=selected_question["id"] if selected_question else "",
                    allowed_user_id=allowed_user_id,
                    row=select_row,
                )
            )


class DebriefQuestionButton(discord.ui.Button):
    """Interactive prompt button sent via DM for post-action report updates."""

    def __init__(
        self,
        *,
        dossier_id: int,
        question: dict[str, Any],
        current_answer: str,
        sol_date: str,
    ):
        qid = question["id"]
        super().__init__(
            label=f"Update [{qid}]",
            style=discord.ButtonStyle.primary,
            custom_id=f"debrief:{dossier_id}:{qid}",
        )
        self.dossier_id = dossier_id
        self.question = question
        self.current_answer = current_answer
        self.sol_date = sol_date

    async def callback(self, interaction: discord.Interaction) -> None:
        modal = DossierAnswerModal(
            dossier_id=self.dossier_id,
            question=self.question,
            current_answer=self.current_answer,
            entry_kind=ENTRY_KIND_POST_ACTION_REPORT,
            sol_date=self.sol_date,
        )
        await interaction.response.send_modal(modal)


class DebriefPromptView(discord.ui.View):
    def __init__(
        self,
        *,
        dossier: CharacterDossier,
        questions: list[dict[str, Any]],
        sol_date: str,
        timeout: float = 900,
    ):
        super().__init__(timeout=timeout)
        responses = dossier.responses if isinstance(dossier.responses, dict) else {}
        for q in questions[:25]:
            qid = q["id"]
            existing = responses.get(qid)
            current_answer = str(existing.get("answer", "")) if isinstance(existing, dict) else ""
            self.add_item(
                DebriefQuestionButton(
                    dossier_id=dossier.pk,
                    question=q,
                    current_answer=current_answer,
                    sol_date=sol_date,
                )
            )


# --------------------------------------------------
# Reusable Command Handlers (Directly Testable)
# --------------------------------------------------


async def handle_link_command(interaction: discord.Interaction, code: str) -> None:
    try:
        username, discord_id, claimed = await _complete_link_async(code, str(interaction.user.id))
    except ValueError as err:
        await interaction.response.send_message(f"Link failed: {err}", ephemeral=True)
        return

    claimed_note = ""
    if claimed:
        claimed_list = ", ".join(f"**{name}**" for name in claimed)
        claimed_note = f" Claimed {len(claimed)} onboarded character dossier(s): {claimed_list}."

    await interaction.response.send_message(
        f"Linked Discord account `{discord_id}` to website user **{username}**.{claimed_note}",
        ephemeral=True,
    )


async def handle_dossier_open_command(
    interaction: discord.Interaction,
    character: str | None = None,
) -> None:
    """Open the character dossier hub with character switcher, intake launcher, and new-character button."""
    try:
        dossier, meta = await _resolve_dossier_async(
            str(interaction.user.id),
            character_identifier=character or "",
            activate=bool(character),
        )
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return

    if meta is None:
        await interaction.response.send_message(
            "Your Discord account is not linked yet. Ask a Storyteller to prompt `/intake`, "
            "or generate a link code on the website and run `/link <code>`.",
            ephemeral=True,
        )
        return

    if dossier is None:
        embed = discord.Embed(
            title="No Character Dossiers Found",
            description=(
                f"Account ready (**{meta['username']}**), but you have not initialized a character narrative yet.\n"
                "Click **+ New Character** below (or run `/dossier create`) to start one."
            ),
            color=discord.Color.blue(),
        )
        view = DossierArchiveView(
            items=[],
            active_dossier=None,
            allowed_user_id=str(interaction.user.id),
            allow_unlinked=bool(meta.get("invited")),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    _auth, _is_linked, items = await _get_actor_dossiers_async(str(interaction.user.id))
    embed = _build_dossier_overview_embed(dossier, meta["stats"], total_characters=len(items))
    view = DossierArchiveView(
        items=items,
        active_dossier=dossier,
        allowed_user_id=str(interaction.user.id),
        allow_unlinked=bool(meta.get("invited")),
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def handle_dossier_swap_command(
    interaction: discord.Interaction,
    character: str,
) -> None:
    """Switch the linked or invited user's active CharacterDossier."""
    try:
        dossier, stats = await _swap_active_dossier_async(str(interaction.user.id), character)
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return

    _auth, _is_linked, items = await _get_actor_dossiers_async(str(interaction.user.id))
    embed = _build_dossier_overview_embed(dossier, stats, total_characters=len(items))
    embed.title = f"Swapped Active Dossier: {dossier.character_name}"[:256]
    view = DossierArchiveView(
        items=items,
        active_dossier=dossier,
        allowed_user_id=str(interaction.user.id),
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def handle_dossier_list_command(
    interaction: discord.Interaction,
    member: discord.Member | discord.User | None = None,
) -> None:
    """List character dossiers for yourself or (if ST/linked) another Discord member."""
    targeting_other = member is not None and str(member.id) != str(interaction.user.id)
    if targeting_other:
        invoker_is_linked, _inv_uid, _inv_name = await _get_link_user_async(str(interaction.user.id))
        if not invoker_is_linked and not _has_discord_st_permissions(interaction.user):
            await interaction.response.send_message(
                "Only linked users or Storytellers/Admins can inspect another member's dossiers.",
                ephemeral=True,
            )
            return
        lookup_id = str(member.id)
        is_authorized, is_linked, items = await _get_actor_dossiers_async(lookup_id)
        if not is_authorized or not items:
            await interaction.response.send_message(
                f"**{member.display_name}** has no Character Dossiers yet. Run `/intake member:@player` or "
                "`/dossier create member:@player` to initialize one.",
                ephemeral=True,
            )
            return
    else:
        is_authorized, is_linked, items = await _get_actor_dossiers_async(str(interaction.user.id))
        if not is_authorized:
            await interaction.response.send_message(
                "Your Discord account is not linked yet. Ask a Storyteller to prompt `/intake`, "
                "or generate a link code on the website and run `/link <code>`.",
                ephemeral=True,
            )
            return

    if not items:
        embed = discord.Embed(
            title="Your Character Dossiers (0)",
            description="No dossiers created yet. Click **+ New Character** below or run `/dossier create`.",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=DossierArchiveView(
                items=[],
                active_dossier=None,
                allowed_user_id=str(interaction.user.id),
                allow_unlinked=not is_linked,
            ),
            ephemeral=True,
        )
        return

    lines: list[str] = []
    active_dossier = items[0]["dossier"]
    for entry in items:
        d = entry["dossier"]
        stats = entry["stats"]
        tag = "**[ACTIVE]** " if entry["is_active"] else ""
        if entry["is_active"]:
            active_dossier = d
        claim_note = "" if d.is_claimed else " _(Unclaimed · awaiting /link)_"
        lines.append(
            f"- {tag}**{d.character_name}** (`{d.slug}`) · {d.get_narrative_voice_display()} · "
            f"Core {stats['core_answered']}/{stats['core_total']}, Total {stats['answered_count']}/{stats['total_questions']}"
            f"{claim_note}"
        )

    title_prefix = f"{member.display_name}'s " if targeting_other and member is not None else ""
    embed = discord.Embed(
        title=f"{title_prefix}Character Dossiers ({len(items)})",
        description="\n".join(lines)[:4096],
        color=discord.Color.teal(),
    )
    if targeting_other:
        embed.set_footer(text="Run `/intake member:@player character:<slug>` to prompt a specific character.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed.set_footer(text="Use the dropdown below or `/dossier swap <character>` to switch active narrative.")
    view = DossierArchiveView(
        items=items,
        active_dossier=active_dossier,
        allowed_user_id=str(interaction.user.id),
        allow_unlinked=not is_linked,
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def handle_dossier_create_command(
    interaction: discord.Interaction,
    member: discord.Member | discord.User | None = None,
) -> None:
    """Open the modal to create a new CharacterDossier for yourself or (if ST/linked) another member."""
    if member is not None and str(member.id) != str(interaction.user.id):
        invoker_is_linked, invoker_user_id, _inv_name = await _get_link_user_async(str(interaction.user.id))
        if not invoker_is_linked and not _has_discord_st_permissions(interaction.user):
            await interaction.response.send_message(
                "Only linked users or Storytellers/Admins can create a character dossier for another member.",
                ephemeral=True,
            )
            return
        target_id = str(member.id)
        await _register_intake_invite_async(target_id, invited_by_user_id=invoker_user_id)
        await interaction.response.send_modal(
            CreateDossierModal(
                allow_unlinked=True,
                invited_by_user_id=invoker_user_id,
                target_discord_user_id=target_id,
                target_display_name=member.display_name,
                target_member=member,
            )
        )
        return

    is_authorized, is_linked, _items = await _get_actor_dossiers_async(str(interaction.user.id))
    if not is_authorized:
        await interaction.response.send_message(
            "Your Discord account is not linked yet. Ask a Storyteller to prompt `/intake`, "
            "or generate a link code on the website and run `/link <code>`.",
            ephemeral=True,
        )
        return
    await interaction.response.send_modal(CreateDossierModal(allow_unlinked=not is_linked))


async def _prompt_target_member_intake(
    interaction: discord.Interaction,
    *,
    member: discord.Member | discord.User,
    category: str | None = None,
    character: str | None = None,
    scope: str | None = None,
    delivery: Literal["dm", "channel"] = "dm",
) -> None:
    invoker_is_linked, invoker_user_id, invoker_username = await _get_link_user_async(str(interaction.user.id))
    has_st_perm = _has_discord_st_permissions(interaction.user)
    if not invoker_is_linked and not has_st_perm:
        await interaction.response.send_message(
            "Only linked users or Storytellers/Admins can prompt intake for another member.",
            ephemeral=True,
        )
        return

    target_id = str(member.id)
    await _register_intake_invite_async(target_id, invited_by_user_id=invoker_user_id)

    clean_char = (character or "").strip()
    created_for_target = False
    try:
        dossier, meta = await _resolve_dossier_async(
            target_id,
            character_identifier=clean_char,
            activate=bool(clean_char),
            allow_unlinked=True,
        )
    except ValueError as err:
        err_msg = str(err)
        if clean_char and "Multiple characters match" not in err_msg:
            dossier, stats = await _create_dossier_async(
                target_id,
                character_name=clean_char,
                allow_unlinked=True,
                invited_by_user_id=invoker_user_id,
            )
            meta = {"stats": stats}
            created_for_target = True
        else:
            await interaction.response.send_message(err_msg, ephemeral=True)
            return

    effective_scope = scope or ("all" if category else "core")
    inviter_label = invoker_username or getattr(interaction.user, "display_name", "Storyteller")

    if dossier is None:
        embed = discord.Embed(
            title="Agent Onboarding & Ego Intake",
            description=(
                f"Welcome, **{member.display_name}**! **{inviter_label}** invited you to initialize a character dossier.\n\n"
                "Click **Create Character & Start Intake** below to name your character and begin answering Core Prompts.\n"
                "Later, when you create or sign into an account on the website and run `/link <code>`, your character(s) "
                "will automatically attach to your account."
            ),
            color=discord.Color.blue(),
        )
        view: discord.ui.View = OnboardingInviteView(
            target_discord_user_id=target_id,
            invited_by_user_id=invoker_user_id,
            scope=effective_scope,
            category=category,
        )
        status_label = "character onboarding invitation"
    else:
        questions, resolved_scope = _filter_intake_questions(
            dossier,
            scope=effective_scope,
            category=category,
        )
        if not questions:
            await interaction.response.send_message(
                f"No prompts match that filter for **{dossier.character_name}**.",
                ephemeral=True,
            )
            return
        embed = _build_intake_overview_embed(
            dossier,
            meta["stats"],
            scope=resolved_scope,
            category=category,
            shown_count=len(questions),
        )
        view = DossierSelectView(
            dossier=dossier,
            questions=questions,
            allowed_user_id=target_id,
        )
        created_note = " *(initialized)*" if created_for_target else ""
        status_label = f"intake prompt for **{dossier.character_name}**{created_note}"

    mention = getattr(member, "mention", f"<@{target_id}>")
    channel = getattr(interaction, "channel", None)
    channel_send = getattr(channel, "send", None)
    channel_can_send = channel is not None and inspect.iscoroutinefunction(channel_send)

    if delivery == "channel":
        if channel_can_send:
            await channel.send(
                content=f"{mention} — **{inviter_label}** opened your Spacemarches character intake:",
                embed=embed,
                view=view,
            )
            await interaction.response.send_message(
                f"Posted {status_label} for **{member.display_name}** in this channel.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            content=f"{mention} — **{inviter_label}** opened your Spacemarches character intake:",
            embed=embed,
            view=view,
        )
        return

    try:
        await member.send(embed=embed, view=view)
    except discord.Forbidden:
        if channel_can_send:
            await channel.send(
                content=(
                    f"{mention} — **{inviter_label}** opened your Spacemarches character intake "
                    "(posted here because your DMs are closed):"
                ),
                embed=embed,
                view=view,
            )
            await interaction.response.send_message(
                f"Could not DM **{member.display_name}**; posted {status_label} in this channel instead.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Could not DM {member.display_name}; their server DMs may be disabled (try `delivery:channel`).",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"Sent {status_label} to **{member.display_name}** via DM (onboarding access enabled).",
        ephemeral=True,
    )


async def handle_intake_command(
    interaction: discord.Interaction,
    category: str | None = None,
    character: str | None = None,
    scope: str | None = None,
    member: discord.Member | discord.User | None = None,
    delivery: Literal["dm", "channel"] = "dm",
) -> None:
    """Start or continue ego intake for yourself or onboard another Discord member."""
    if member is not None and str(member.id) != str(interaction.user.id):
        await _prompt_target_member_intake(
            interaction,
            member=member,
            category=category,
            character=character,
            scope=scope,
            delivery=delivery,
        )
        return

    try:
        dossier, meta = await _resolve_dossier_async(
            str(interaction.user.id),
            character_identifier=character or "",
            activate=bool(character),
        )
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return

    if meta is None:
        await interaction.response.send_message(
            "Your Discord account is not linked yet. Ask a Storyteller/linked player to prompt you with "
            "`/intake member:@you`, or generate a link code on the website and run `/link <code>`.",
            ephemeral=True,
        )
        return
    if dossier is None:
        embed = discord.Embed(
            title="Initialize Your First Character",
            description=(
                f"Onboarding enabled (**{meta['username']}**), and you have not created a Character Dossier yet.\n"
                "Click **Create Character & Start Intake** below to name your character and begin."
            ),
            color=discord.Color.blue(),
        )
        view = discord.ui.View(timeout=300)
        view.add_item(
            CreateDossierButton(
                label="Create Character & Start Intake",
                style=discord.ButtonStyle.primary,
                allowed_user_id=str(interaction.user.id),
                allow_unlinked=bool(meta.get("invited")) or not bool(meta.get("linked")),
                start_intake_on_create=True,
                scope=scope or ("all" if category else "core"),
                category=category,
            )
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return

    effective_scope = scope or ("all" if category else "core")
    questions, resolved_scope = _filter_intake_questions(
        dossier,
        scope=effective_scope,
        category=category,
    )
    if not questions:
        await interaction.response.send_message(
            f"No prompts match that filter for **{dossier.character_name}**.",
            ephemeral=True,
        )
        return

    stats = meta["stats"]
    embed = _build_intake_overview_embed(
        dossier,
        stats,
        scope=resolved_scope,
        category=category,
        shown_count=len(questions),
    )
    view = DossierSelectView(
        dossier=dossier,
        questions=questions,
        allowed_user_id=str(interaction.user.id),
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def handle_dossier_command(
    interaction: discord.Interaction,
    category: str | None = None,
    character: str | None = None,
) -> None:
    """Compatibility helper mapping directly to the interactive intake questionnaire."""
    await handle_intake_command(
        interaction,
        category=category,
        character=character,
        scope="all" if category else "core",
    )


async def handle_debrief_command(
    interaction: discord.Interaction,
    member: discord.Member | discord.User,
    stardate: str = "",
    question_ids: str = "",
    *,
    character: str = "",
    session_tag: str = "",
) -> None:
    invoker_is_linked, _inv_uid, _inv_name = await _get_link_user_async(str(interaction.user.id))
    has_st_perm = _has_discord_st_permissions(interaction.user)
    is_real_discord_user = isinstance(interaction.user, (discord.Member, discord.User))
    if is_real_discord_user and not invoker_is_linked and not has_st_perm:
        await interaction.response.send_message(
            "Only linked users or Storytellers/Admins can send debrief prompts.",
            ephemeral=True,
        )
        return

    raw_stardate = (stardate or session_tag or "").strip()
    try:
        _era, _sol_num, canonical_sol = normalize_stardate("", raw_stardate)
    except ValueError as err:
        await interaction.response.send_message(f"Invalid stardate: {err}", ephemeral=True)
        return

    raw_ids = [item.strip() for item in (question_ids or "").split(",") if item.strip()]
    if not raw_ids:
        await interaction.response.send_message(
            "Provide one or more comma-separated question IDs (e.g. `15a,15b,6.1d`).",
            ephemeral=True,
        )
        return

    valid_questions: list[dict[str, Any]] = []
    invalid_ids: list[str] = []
    for qid in raw_ids:
        q = get_question(qid)
        if q is None:
            invalid_ids.append(qid)
        else:
            valid_questions.append(q)

    if invalid_ids:
        await interaction.response.send_message(
            f"Unknown question ID(s): {', '.join(invalid_ids)}",
            ephemeral=True,
        )
        return

    try:
        dossier, meta = await _resolve_dossier_async(
            str(member.id),
            character_identifier=character,
            activate=False,
        )
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return

    if meta is None or dossier is None:
        await interaction.response.send_message(
            f"Target user {member.display_name} does not have a Character Dossier yet. "
            "Prompt `/intake member:@player` first to help them create one.",
            ephemeral=True,
        )
        return

    visible_questions = [
        q
        for q in valid_questions
        if q.get("tier") != "sensitive_appendix" or dossier.show_sensitive_appendix
    ]
    if not visible_questions:
        await interaction.response.send_message(
            "Requested questions are gated under Sensitive Appendix and the player has not opted in.",
            ephemeral=True,
        )
        return

    prompt_lines = "\n".join(f"- **[{q['id']}]** {q['prompt']}" for q in visible_questions)
    dm_embed = discord.Embed(
        title=f"Post-Action Report: {canonical_sol}",
        description=(
            f"Character: **{dossier.character_name}**\n"
            f"Requested progression updates as of **{canonical_sol}**:\n\n{prompt_lines}"
        ),
        color=discord.Color.teal(),
    )
    view = DebriefPromptView(
        dossier=dossier,
        questions=visible_questions,
        sol_date=canonical_sol,
    )

    try:
        await member.send(embed=dm_embed, view=view)
    except discord.Forbidden:
        await interaction.response.send_message(
            f"Could not DM {member.display_name}; their server DMs may be disabled.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"Sent Post-Action Report debrief ({canonical_sol}) for {', '.join(q['id'] for q in visible_questions)} "
        f"({dossier.character_name}) to {member.display_name}.",
        ephemeral=True,
    )


# --------------------------------------------------
# Bot Factory & Management Command
# --------------------------------------------------


def build_bot(*, guild_id: int | None = None) -> discord.Client:
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    _category_choices = [
        app_commands.Choice(name=cat[:100], value=cat[:100])
        for cat in get_categories(include_sensitive=False)[:25]
    ]

    async def _character_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        namespace = getattr(interaction, "namespace", None)
        target_member = getattr(namespace, "member", None) if namespace is not None else None
        target_id = getattr(target_member, "id", None)
        if not target_id and isinstance(target_member, (int, str)) and str(target_member).strip():
            target_id = str(target_member).strip()
        lookup_id = str(target_id or interaction.user.id)

        _auth, _is_linked, items = await _get_actor_dossiers_async(lookup_id)
        cur = (current or "").strip().lower()
        choices: list[app_commands.Choice[str]] = []
        for entry in items:
            d = entry["dossier"]
            if cur and cur not in d.character_name.lower() and cur not in d.slug.lower():
                continue
            prefix = "★ " if entry["is_active"] else ""
            label = f"{prefix}{d.character_name}"[:100]
            value = d.slug if len(d.slug) <= 100 else str(d.pk)
            choices.append(app_commands.Choice(name=label, value=value))
        return choices[:25]

    @tree.command(name="link", description="Link your Discord account to your Spacemarches account.")
    @app_commands.describe(code="One-time link code generated from /spacemarches/dossier/")
    async def link_cmd(interaction: discord.Interaction, code: str):
        await handle_link_command(interaction, code)

    dossier_group = app_commands.Group(
        name="dossier",
        description="Select, swap, or initialize your character dossiers.",
    )

    @dossier_group.command(name="open", description="Open your character dossier overview and switcher.")
    @app_commands.describe(character="Optional character name or slug to open and make active")
    @app_commands.autocomplete(character=_character_autocomplete)
    async def dossier_open_cmd(interaction: discord.Interaction, character: str | None = None):
        await handle_dossier_open_command(interaction, character=character)

    @dossier_group.command(name="swap", description="Switch which character dossier is currently active.")
    @app_commands.describe(character="Character name or slug to activate")
    @app_commands.autocomplete(character=_character_autocomplete)
    async def dossier_swap_cmd(interaction: discord.Interaction, character: str):
        await handle_dossier_swap_command(interaction, character=character)

    @dossier_group.command(name="list", description="List character dossiers for yourself or (ST/linked) another member.")
    @app_commands.describe(member="Optional Discord member whose character dossiers you want to inspect")
    async def dossier_list_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
        await handle_dossier_list_command(interaction, member=member)

    @dossier_group.command(name="create", description="Initialize a new character dossier for yourself or another member.")
    @app_commands.describe(member="Optional Discord member to initialize the character dossier for")
    async def dossier_create_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
        await handle_dossier_create_command(interaction, member=member)

    tree.add_command(dossier_group)

    @tree.command(
        name="intake",
        description="Begin ego intake for yourself or prompt/onboard another Discord member.",
    )
    @app_commands.describe(
        member="ST / Linked User: optionally target another Discord member to onboard/prompt",
        character="Optional character name or slug (creates on target member if new)",
        scope="Prompt tier filter (defaults to Core Prompts unless a category is picked)",
        category="Optional category filter",
        delivery="When targeting a member: send via DM (with channel fallback) or post in channel",
    )
    @app_commands.autocomplete(character=_character_autocomplete)
    @app_commands.choices(category=_category_choices)
    async def intake_cmd(
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        character: str | None = None,
        scope: Literal["core", "all", "unanswered"] | None = None,
        category: str | None = None,
        delivery: Literal["dm", "channel"] = "dm",
    ):
        await handle_intake_command(
            interaction,
            category=category,
            character=character,
            scope=scope,
            member=member,
            delivery=delivery,
        )

    @tree.command(name="debrief", description="GM: DM a player interactive post-action report prompts.")
    @app_commands.describe(
        member="Target Discord member",
        stardate="Pre-Fall, Fall, or Post-Fall Sol-date (e.g. 2.450)",
        question_ids="Comma-separated question IDs (e.g. 15a,15b,6.1d)",
        character="Optional player character name/slug (defaults to their active dossier)",
    )
    @app_commands.autocomplete(character=_character_autocomplete)
    async def debrief_cmd(
        interaction: discord.Interaction,
        member: discord.Member,
        stardate: str,
        question_ids: str,
        character: str | None = None,
    ):
        await handle_debrief_command(
            interaction,
            member,
            stardate=stardate,
            question_ids=question_ids,
            character=character or "",
        )

    @client.event
    async def on_ready():
        if guild_id:
            guild_obj = discord.Object(id=int(guild_id))
            tree.copy_global_to(guild=guild_obj)
            await tree.sync(guild=guild_obj)
        else:
            await tree.sync()

    client.tree = tree
    return client


class Command(BaseCommand):
    help = "Run the Spacemarches Discord bot bridging slash commands to dossier_service."

    def add_arguments(self, parser):
        parser.add_argument(
            "--token",
            default="",
            help="Discord bot token override (defaults to settings.DISCORD_BOT_TOKEN / env DISCORD_BOT_TOKEN).",
        )
        parser.add_argument(
            "--guild-id",
            default="",
            help="Optional Discord server (guild) ID for instant slash-command sync (defaults to env DISCORD_GUILD_ID).",
        )

    def handle(self, *args, **options):
        token = (
            options.get("token")
            or getattr(settings, "DISCORD_BOT_TOKEN", "")
            or os.environ.get("DISCORD_BOT_TOKEN", "")
        ).strip()
        if not token:
            raise CommandError(
                "DISCORD_BOT_TOKEN is not configured. Set DISCORD_BOT_TOKEN in the environment or pass --token."
            )

        raw_guild_id = (
            options.get("guild_id")
            or getattr(settings, "DISCORD_GUILD_ID", "")
            or os.environ.get("DISCORD_GUILD_ID", "")
        )
        guild_id: int | None = None
        if str(raw_guild_id or "").strip():
            try:
                guild_id = int(str(raw_guild_id).strip())
            except ValueError as err:
                raise CommandError(f"Invalid guild ID '{raw_guild_id}': must be a numeric Discord server ID.") from err

        bot = build_bot(guild_id=guild_id)
        self.stdout.write(self.style.SUCCESS("Starting Spacemarches Discord bot..."))
        bot.run(token)
