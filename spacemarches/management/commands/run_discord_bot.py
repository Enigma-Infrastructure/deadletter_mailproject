"""Django management command running the Spacemarches Discord dossier bot."""
from __future__ import annotations

import os
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import discord
from discord import app_commands

from spacemarches.models import CharacterDossier, DiscordLink
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
    normalize_stardate,
    save_dossier_answer,
)


# --------------------------------------------------
# Sync-to-Async DB Helpers
# --------------------------------------------------


@sync_to_async
def _complete_link_async(code: str, discord_user_id: str) -> tuple[str, str]:
    link = complete_discord_link(code=code, discord_user_id=discord_user_id)
    return str(link.user), link.discord_user_id or ""


@sync_to_async
def _get_active_dossier_for_discord(discord_user_id: str) -> tuple[CharacterDossier | None, dict[str, Any] | None]:
    link = (
        DiscordLink.objects.select_related("user")
        .filter(discord_user_id=str(discord_user_id))
        .first()
    )
    if link is None:
        return None, None
    dossier = (
        CharacterDossier.objects.filter(user=link.user)
        .order_by("-updated_at")
        .first()
    )
    if dossier is None:
        return None, {"linked": True, "username": str(link.user)}
    stats = compute_dossier_stats(dossier)
    return dossier, {"linked": True, "username": str(link.user), "stats": stats}


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


# --------------------------------------------------
# Discord UI Components (Modals, Select, Debrief Buttons)
# --------------------------------------------------


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


class DossierEditButton(discord.ui.Button):
    """Opens the answer modal while keeping the unclipped prompt visible above."""

    def __init__(
        self,
        *,
        dossier: CharacterDossier,
        question: dict[str, Any],
        session_tag: str = "",
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

    async def callback(self, interaction: discord.Interaction) -> None:
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
        row: int = 0,
    ):
        self.dossier = dossier
        self.questions = questions
        self.session_tag = session_tag
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
        username, discord_id = await _complete_link_async(code, str(interaction.user.id))
    except ValueError as err:
        await interaction.response.send_message(f"Link failed: {err}", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Linked Discord account `{discord_id}` to website user **{username}**.",
        ephemeral=True,
    )


async def handle_dossier_command(
    interaction: discord.Interaction,
    category: str | None = None,
) -> None:
    dossier, meta = await _get_active_dossier_for_discord(str(interaction.user.id))
    if meta is None:
        await interaction.response.send_message(
            "Your Discord account is not linked yet. Generate a link code on the website and run `/link <code>`.",
            ephemeral=True,
        )
        return
    if dossier is None:
        await interaction.response.send_message(
            f"Linked to **{meta['username']}**, but no Character Dossier exists yet. Create one at `/spacemarches/dossier/`.",
            ephemeral=True,
        )
        return

    questions = get_all_questions(include_sensitive=dossier.show_sensitive_appendix)
    if category:
        cat_lower = category.strip().lower()
        filtered = [q for q in questions if cat_lower in q.get("category", "").lower()]
        if filtered:
            questions = filtered

    stats = meta["stats"]
    embed = discord.Embed(
        title=f"Dossier: {dossier.character_name}",
        description=(
            f"Voice: **{dossier.get_narrative_voice_display()}**\n"
            f"Core: **{stats['core_answered']}/{stats['core_total']}** | "
            f"Total: **{stats['answered_count']}/{stats['total_questions']}** "
            f"({stats['completion_percent']}%)"
        ),
        color=discord.Color.blue(),
    )
    if category:
        embed.set_footer(text=f"Filtered by category matching: {category}")

    view = DossierSelectView(dossier=dossier, questions=questions)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def handle_debrief_command(
    interaction: discord.Interaction,
    member: discord.Member | discord.User,
    stardate: str = "",
    question_ids: str = "",
    *,
    session_tag: str = "",
) -> None:
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

    dossier, meta = await _get_active_dossier_for_discord(str(member.id))
    if meta is None or dossier is None:
        await interaction.response.send_message(
            f"Target user {member.display_name} does not have a linked Character Dossier.",
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
        f"Sent Post-Action Report debrief ({canonical_sol}) for {', '.join(q['id'] for q in visible_questions)} to {member.display_name}.",
        ephemeral=True,
    )


# --------------------------------------------------
# Bot Factory & Management Command
# --------------------------------------------------


def build_bot() -> discord.Client:
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @tree.command(name="link", description="Link your Discord account to your Spacemarches account.")
    @app_commands.describe(code="One-time link code generated from /spacemarches/dossier/")
    async def link_cmd(interaction: discord.Interaction, code: str):
        await handle_link_command(interaction, code)

    @tree.command(name="dossier", description="Open your private character dossier progress & prompt editor.")
    @app_commands.describe(category="Optional category filter")
    async def dossier_cmd(interaction: discord.Interaction, category: str | None = None):
        await handle_dossier_command(interaction, category=category)

    @dossier_cmd.autocomplete("category")
    async def dossier_category_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        cur = (current or "").lower()
        return [
            app_commands.Choice(name=cat[:100], value=cat[:100])
            for cat in get_categories(include_sensitive=False)
            if cur in cat.lower()
        ][:25]

    @tree.command(name="debrief", description="GM: DM a linked player interactive post-action report prompts.")
    @app_commands.describe(
        member="Target Discord member",
        stardate="Pre-Fall, Fall, or Post-Fall Sol-date (e.g. 2.450)",
        question_ids="Comma-separated question IDs (e.g. 15a,15b,6.1d)",
    )
    async def debrief_cmd(
        interaction: discord.Interaction,
        member: discord.Member,
        stardate: str,
        question_ids: str,
    ):
        await handle_debrief_command(interaction, member, stardate=stardate, question_ids=question_ids)

    @client.event
    async def on_ready():
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

        bot = build_bot()
        self.stdout.write(self.style.SUCCESS("Starting Spacemarches Discord bot..."))
        bot.run(token)
