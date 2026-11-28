"""Discord interactive views and slash-command handlers for EP2e Life Path creation."""
from __future__ import annotations

import io
from typing import Any

from asgiref.sync import sync_to_async
import discord

from spacemarches.models import DiscordLink, LifepathEntry, LifepathSession, LifepathTable
from spacemarches.services.lifepath_service import (
    APT_KEYS,
    CAREER_TO_GEAR_PACK,
    STEP_TITLES,
    apply_step15_gear_packs,
    compute_final_sheet,
    ensure_lifepath_seeded,
    finalize_and_export_session,
    get_active_lifepath_session,
    get_choice_options_for_pending,
    perform_step_roll,
    reallocate_step15_overflow,
    render_lifepath_summary_markdown,
    resolve_pending_choice,
    skip_optional_step,
    start_lifepath_session,
    use_flex_reroll,
)

SELECT_PAGE_SIZE = 25


def _trunc(text: str, limit: int) -> str:
    txt = str(text or "").strip()
    if len(txt) <= limit:
        return txt
    return txt[: max(1, limit - 1)].rstrip() + "…"


# ---------------------------------------------------------------------------
# Sync-to-async DB wrappers
# ---------------------------------------------------------------------------


@sync_to_async
def _start_session_async(
    *,
    discord_user_id: str,
    character_name: str,
    channel_id: str = "",
    hardcore_flex: bool = False,
    archive_existing: bool = True,
) -> LifepathSession:
    did = str(discord_user_id or "").strip()
    link = DiscordLink.objects.select_related("user", "active_dossier").filter(discord_user_id=did).first()
    user = link.user if link else None
    dossier = link.active_dossier if link else None
    if archive_existing:
        LifepathSession.objects.filter(
            discord_user_id=did,
            status=LifepathSession.STATUS_IN_PROGRESS,
        ).update(status=LifepathSession.STATUS_ARCHIVED)
    return start_lifepath_session(
        character_name=character_name or "Unnamed Lifepath Ego",
        user=user,
        discord_user_id=did,
        discord_channel_id=channel_id,
        hardcore_flex=hardcore_flex,
        dossier=dossier,
    )


@sync_to_async
def _get_session_async(
    *,
    session_id: int | None = None,
    discord_user_id: str = "",
    include_completed: bool = True,
) -> LifepathSession | None:
    if session_id is not None:
        return LifepathSession.objects.select_related("user", "generated_character", "dossier").filter(pk=session_id).first()
    return get_active_lifepath_session(discord_user_id=discord_user_id, include_completed=include_completed)


@sync_to_async
def _get_render_context_async(session_id: int) -> dict[str, Any]:
    ensure_lifepath_seeded()
    session = LifepathSession.objects.select_related("user", "generated_character", "dossier").get(pk=session_id)
    state = session.state or {}
    pending_choices = state.get("pending_choices") or []
    pending_sub_rolls = state.get("pending_sub_rolls") or []

    active_choice = pending_choices[0] if pending_choices else None
    choice_options = get_choice_options_for_pending(active_choice) if active_choice else []

    active_slug = ""
    if pending_sub_rolls:
        active_slug = pending_sub_rolls[0].get("table_slug", "")
    elif not active_choice:
        active_slug = state.get("active_table_slug") or ""

    table = LifepathTable.objects.filter(slug=active_slug, is_active=True).first() if active_slug else None
    table_entries = list(table.entries.filter(is_active=True)) if table else []

    # Step 15 choices
    camp_packs = []
    prof_packs = []
    if session.current_step >= 15:
        camp_tbl = LifepathTable.objects.filter(slug="gear-pack-campaign", is_active=True).first()
        prof_tbl = LifepathTable.objects.filter(slug="gear-pack-profession", is_active=True).first()
        if camp_tbl:
            camp_packs = list(camp_tbl.entries.filter(is_active=True))
        if prof_tbl:
            prof_packs = list(prof_tbl.entries.filter(is_active=True))

    sheet = compute_final_sheet(state)
    return {
        "session": session,
        "table": table,
        "table_entries": table_entries,
        "active_choice": active_choice,
        "choice_options": choice_options,
        "pending_sub_roll": pending_sub_rolls[0] if pending_sub_rolls else None,
        "camp_packs": camp_packs,
        "prof_packs": prof_packs,
        "sheet": sheet,
    }


@sync_to_async
def _perform_roll_async(
    session_id: int,
    *,
    table_slug: str | None = None,
    chosen_entry_code: str | None = None,
) -> tuple[LifepathSession, dict[str, Any]]:
    session = LifepathSession.objects.get(pk=session_id)
    res = perform_step_roll(session, table_slug=table_slug, chosen_entry_code=chosen_entry_code)
    return session, res


@sync_to_async
def _reroll_flex_async(session_id: int) -> tuple[LifepathSession, dict[str, Any]]:
    session = LifepathSession.objects.get(pk=session_id)
    res = use_flex_reroll(session)
    return session, res


@sync_to_async
def _resolve_choice_async(
    session_id: int,
    *,
    selected_value: str | None = None,
    auto_roll: bool = False,
) -> tuple[LifepathSession, dict[str, Any]]:
    session = LifepathSession.objects.get(pk=session_id)
    res = resolve_pending_choice(session, selected_value=selected_value, auto_roll=auto_roll)
    return session, res


@sync_to_async
def _skip_step_async(session_id: int, reason: str = "Skipped") -> LifepathSession:
    session = LifepathSession.objects.get(pk=session_id)
    return skip_optional_step(session, reason=reason)


@sync_to_async
def _apply_step15_packs_async(
    session_id: int,
    *,
    campaign_pack: str | None = None,
    profession_pack: str | None = None,
    motivations: list[str] | None = None,
) -> dict[str, Any]:
    session = LifepathSession.objects.get(pk=session_id)
    return apply_step15_gear_packs(
        session,
        campaign_pack_title=campaign_pack,
        profession_pack_title=profession_pack,
        selected_motivations=motivations,
    )


@sync_to_async
def _reallocate_overflow_async(
    session_id: int,
    *,
    source_name: str,
    target_name: str,
    amount: int | None = None,
) -> dict[str, Any]:
    session = LifepathSession.objects.get(pk=session_id)
    return reallocate_step15_overflow(
        session,
        source_name=source_name,
        target_name=target_name,
        amount=amount,
    )


@sync_to_async
def _finalize_session_async(
    session_id: int,
    *,
    discord_user_id: str,
    character_name: str | None = None,
    create_dossier: bool = False,
) -> tuple[LifepathSession, Any]:
    session = LifepathSession.objects.get(pk=session_id)
    link = DiscordLink.objects.select_related("user").filter(discord_user_id=str(discord_user_id)).first()
    user = link.user if link else session.user
    return finalize_and_export_session(
        session,
        user=user,
        character_name=character_name,
        create_dossier=create_dossier,
    )


@sync_to_async
def _render_markdown_async(session_id: int) -> tuple[str, str]:
    session = LifepathSession.objects.get(pk=session_id)
    return session.character_name, render_lifepath_summary_markdown(session)


@sync_to_async
def _find_choose_autocomplete_async(discord_user_id: str, current: str) -> list[tuple[str, str]]:
    session = get_active_lifepath_session(discord_user_id=discord_user_id, include_completed=False)
    if session is None:
        return []
    state = session.state or {}
    pending = state.get("pending_choices") or []
    needle = (current or "").strip().lower()
    if pending:
        opts = get_choice_options_for_pending(pending[0])
        matches = [
            (o["label"], o["value"])
            for o in opts
            if not needle or needle in o["label"].lower()
        ]
        return matches[:25]
    slug = state.get("active_table_slug") or ""
    if not slug:
        return []
    table = LifepathTable.objects.filter(slug=slug, is_active=True).first()
    if table is None or not table.allow_choice:
        return []
    entries = table.entries.filter(is_active=True)
    out = []
    for e in entries:
        if e.effects and (e.effects.get("flags") or {}).get("reroll_sub"):
            continue
        label = f"[{e.roll_display}] {e.title}"
        if not needle or needle in label.lower():
            out.append((label, e.code))
    return out[:25]


# ---------------------------------------------------------------------------
# Embed & UI View Builders
# ---------------------------------------------------------------------------


def build_lifepath_embed(ctx: dict[str, Any]) -> discord.Embed:
    """Build the rich interactive Embed representing the current Lifepath state."""
    session: LifepathSession = ctx["session"]
    state = session.state or {}
    sheet: dict[str, Any] = ctx["sheet"]
    table: LifepathTable | None = ctx["table"]
    active_choice: dict[str, Any] | None = ctx["active_choice"]
    pending_sub: dict[str, Any] | None = ctx["pending_sub_roll"]

    step_num = int(session.current_step)
    step_title = STEP_TITLES.get(step_num, f"Step {step_num}")
    if session.status == LifepathSession.STATUS_COMPLETED:
        color = discord.Color.green()
        status_tag = "COMPLETED"
    elif active_choice:
        color = discord.Color.gold()
        status_tag = "CHOICE REQUIRED"
    else:
        color = discord.Color.teal()
        status_tag = step_title

    embed = discord.Embed(
        title=_trunc(f"EP2e Life Path: {sheet['character_name']}", 256),
        description=f"**{status_tag}** · Step `{step_num}/15`\n"
        + (
            f"Hardcore Flex Mode · Starting Flex `{sheet['flex']}` · Rerolls Left `{sheet['flex_rerolls_remaining']}`"
            if session.hardcore_flex
            else f"Ego Flex `{sheet['flex']}` · Flex Rerolls Left `{sheet['flex_rerolls_remaining']}`"
        ),
        color=color,
    )

    # Aptitudes & Identity summary
    apt_line = " | ".join(f"**{k.upper()}** `{sheet['aptitudes'][k]}`" for k in APT_KEYS)
    embed.add_field(name="Aptitudes", value=apt_line, inline=False)

    id_parts = [
        f"**Background:** {sheet['background'] or '—'}",
        f"**Age:** {sheet['age_label'] or '—'}",
        f"**Morph:** {sheet['morph'].get('name') or '—'}",
        f"**Career:** {sheet['career'] or '—'}",
        f"**Interest:** {sheet['interest'] or '—'}",
        f"**Faction:** {sheet['faction'] or '—'}",
    ]
    embed.add_field(name="Identity & Path", value=_trunc("\n".join(id_parts), 1024), inline=True)

    # Top stats / traits / rep snapshot
    rep_str = ", ".join(f"{k} {v}" for k, v in sheet["reputations"].items()) or "—"
    tr_str = ", ".join(f"{t['name']} ({t['level']})" for t in sheet["traits"][:6]) or "—"
    if len(sheet["traits"]) > 6:
        tr_str += f" (+{len(sheet['traits'])-6} more)"
    lang_str = ", ".join(sheet["languages"]) or "—"
    stat_parts = [
        f"**Languages:** {lang_str}",
        f"**Rep:** {rep_str}",
        f"**Traits:** {tr_str}",
        f"**Skills:** {len(sheet['active_skills'])} active / {len(sheet['know_skills'])} know",
    ]
    if sheet["sleights"]:
        stat_parts.append(f"**Sleights:** {len(sheet['sleights'])} ({', '.join(s['name'] for s in sheet['sleights'][:4])})")
    embed.add_field(name="Accumulated Modifiers", value=_trunc("\n".join(stat_parts), 1024), inline=True)

    # Last roll feedback
    last_roll = state.get("last_roll")
    if isinstance(last_roll, dict):
        hl = last_roll.get("highlights") or []
        hl_txt = ("\n**Effects:** " + ", ".join(hl)) if hl else ""
        roll_body = (
            f"**{last_roll.get('table_name', '')}** (`{last_roll.get('roll', '')}`)\n"
            f"Result: **{last_roll.get('entry_title', '')}**\n"
            f"{last_roll.get('summary', '')}{hl_txt}"
        )
        embed.add_field(name="Latest Roll", value=_trunc(roll_body, 1024), inline=False)

    # Current prompt / Step 15 summary
    if active_choice:
        embed.add_field(
            name="Action Needed (Choice)",
            value=_trunc(active_choice.get("prompt", "Choose an option below."), 1024),
            inline=False,
        )
    elif pending_sub:
        embed.add_field(
            name="Follow-Up Roll Queued",
            value=_trunc(f"Triggered roll: **{pending_sub.get('reason', pending_sub.get('table_slug'))}**", 1024),
            inline=False,
        )
    elif step_num == 13 and table is None:
        embed.add_field(
            name="Campaign Event",
            value="Choose which Campaign table matches your game (**Firewall**, **Gatecrashing**, or **Crime**), or skip Step 13.",
            inline=False,
        )
    elif step_num == 15:
        d = sheet["derived"]
        derived_txt = (
            f"INIT `{d['initiative']}` · LUC `{d['lucidity']}` · TT `{d['trauma_threshold']}` · IR `{d['insanity_rating']}`"
            + (f" · Infection `{d['infection_rating']}`" if d["infection_rating"] else "")
            + f"\n**Motivations:** {', '.join(sheet['motivations']) or 'Pick up to 3 below'}"
            + f"\n**Gear Packs:** Campaign `{sheet['gear_pack_campaign'] or 'Not picked'}` · Profession `{sheet['gear_pack_profession'] or 'Not picked'}`"
        )
        if sheet["skill_overflows"] or sheet["rep_overflows"]:
            ov_list = [f"{o['skill']} ({o['total']} -> +{o['excess']} over 80)" for o in sheet["skill_overflows"]]
            ov_list += [f"{o['rep']} ({o['total']} -> +{o['excess']} over 80)" for o in sheet["rep_overflows"]]
            derived_txt += "\n⚠️ **Over 80 Cap:** " + ", ".join(ov_list)
        embed.add_field(name="Step 15: Derived Stats & Gear", value=_trunc(derived_txt, 1024), inline=False)
    elif table is not None:
        mode_note = "Roll or Choose below." if table.allow_choice else "Roll below (or spend Ego Flex to reroll afterward)."
        embed.add_field(
            name=f"Next: {table.name}",
            value=_trunc(f"{table.description}\n*{mode_note}*", 1024),
            inline=False,
        )

    if session.generated_character_id:
        embed.set_footer(text=f"Saved as Life Path Character #{session.generated_character_id} · Session #{session.pk}")
    else:
        embed.set_footer(text=f"Lifepath Session #{session.pk} · Use Flex Reroll anytime right after a roll")
    return embed


class CustomTextChoiceModal(discord.ui.Modal):
    def __init__(self, *, session_id: int, prompt: str, allowed_user_id: str):
        super().__init__(title="Life Path Custom Input")
        self.session_id = session_id
        self.allowed_user_id = allowed_user_id
        self.text_input = discord.ui.TextInput(
            label=_trunc(prompt or "Enter value", 45),
            required=True,
            max_length=120,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.allowed_user_id):
            await interaction.response.send_message("This Life Path session belongs to another player.", ephemeral=True)
            return
        await _resolve_choice_async(self.session_id, selected_value=str(self.text_input.value or ""))
        ctx = await _get_render_context_async(self.session_id)
        await interaction.response.edit_message(
            embed=build_lifepath_embed(ctx),
            view=LifepathHubView(ctx, allowed_user_id=self.allowed_user_id),
        )


class FinalizeNameModal(discord.ui.Modal):
    def __init__(self, *, session_id: int, current_name: str, allowed_user_id: str):
        super().__init__(title="Finalize & Save Life Path Character")
        self.session_id = session_id
        self.allowed_user_id = allowed_user_id
        self.name_input = discord.ui.TextInput(
            label="Character Name / Callsign",
            default=_trunc(current_name, 100),
            required=True,
            max_length=160,
        )
        self.dossier_input = discord.ui.TextInput(
            label="Also create linked Dossier? (yes/no)",
            default="no",
            required=False,
            max_length=10,
        )
        self.add_item(self.name_input)
        self.add_item(self.dossier_input)

    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.allowed_user_id):
            await interaction.response.send_message("This Life Path session belongs to another player.", ephemeral=True)
            return
        create_dos = str(self.dossier_input.value or "").strip().lower() in {"y", "yes", "true", "1"}
        session, gen_char = await _finalize_session_async(
            self.session_id,
            discord_user_id=str(interaction.user.id),
            character_name=str(self.name_input.value or "").strip(),
            create_dossier=create_dos,
        )
        ctx = await _get_render_context_async(self.session_id)
        note = (
            f"Saved **{session.character_name}** to your Spacemarches Character Roster (Sheet `#{gen_char.pk}`)."
            if gen_char
            else f"Completed **{session.character_name}**! Run `/link <code>` on the website and re-save to attach to your web account."
        )
        await interaction.response.edit_message(
            content=note,
            embed=build_lifepath_embed(ctx),
            view=LifepathHubView(ctx, allowed_user_id=self.allowed_user_id),
        )


class ReallocateOverflowModal(discord.ui.Modal):
    def __init__(self, *, session_id: int, source_name: str, excess: int, allowed_user_id: str):
        super().__init__(title="Reassign Skill / Rep Overflow (>80)")
        self.session_id = session_id
        self.source_name = source_name
        self.excess = excess
        self.allowed_user_id = allowed_user_id
        self.target_input = discord.ui.TextInput(
            label=_trunc(f"Target skill/rep for {excess} pts from {source_name}", 45),
            placeholder="e.g. Perceive or Know: History or c-rep",
            required=True,
            max_length=80,
        )
        self.add_item(self.target_input)

    async def on_submit(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.allowed_user_id):
            await interaction.response.send_message("This Life Path session belongs to another player.", ephemeral=True)
            return
        try:
            await _reallocate_overflow_async(
                self.session_id,
                source_name=self.source_name,
                target_name=str(self.target_input.value or "").strip(),
                amount=self.excess,
            )
        except ValueError as err:
            await interaction.response.send_message(str(err), ephemeral=True)
            return
        ctx = await _get_render_context_async(self.session_id)
        await interaction.response.edit_message(
            embed=build_lifepath_embed(ctx),
            view=LifepathHubView(ctx, allowed_user_id=self.allowed_user_id),
        )


class _LifepathButton(discord.ui.Button):
    async def callback(self, interaction: discord.Interaction):
        await handle_lifepath_component_interaction(
            interaction,
            custom_id=str(self.custom_id or ""),
            data={"custom_id": self.custom_id},
        )


class _LifepathSelect(discord.ui.Select):
    async def callback(self, interaction: discord.Interaction):
        await handle_lifepath_component_interaction(
            interaction,
            custom_id=str(self.custom_id or ""),
            data={"custom_id": self.custom_id, "values": list(self.values)},
        )


class LifepathHubView(discord.ui.View):
    """Stateful/persistent Discord UI driving the entire 15-step Life Path workflow."""

    def __init__(
        self,
        ctx: dict[str, Any],
        *,
        allowed_user_id: str,
        page: int = 0,
    ):
        super().__init__(timeout=None)
        self.session: LifepathSession = ctx["session"]
        self.allowed_user_id = str(allowed_user_id)
        self.page = max(0, int(page))

        sid = self.session.pk
        state = self.session.state or {}
        table: LifepathTable | None = ctx["table"]
        table_entries: list[LifepathEntry] = ctx["table_entries"]
        active_choice: dict[str, Any] | None = ctx["active_choice"]
        choice_options: list[dict[str, str]] = ctx["choice_options"]
        pending_sub: dict[str, Any] | None = ctx["pending_sub_roll"]
        sheet: dict[str, Any] = ctx["sheet"]
        step_num = int(self.session.current_step)

        can_reroll = bool(
            self.session.status == LifepathSession.STATUS_IN_PROGRESS
            and state.get("step_snapshot")
            and state.get("last_roll")
            and int(state.get("flex_rerolls_remaining", 0)) > 0
        )

        # --- Case 1: Active pending choice ---
        if active_choice:
            if choice_options:
                total_pages = max(1, (len(choice_options) + SELECT_PAGE_SIZE - 1) // SELECT_PAGE_SIZE)
                cur_page = min(self.page, total_pages - 1)
                slice_opts = choice_options[cur_page * SELECT_PAGE_SIZE : (cur_page + 1) * SELECT_PAGE_SIZE]
                sel = _LifepathSelect(
                    placeholder=_trunc(active_choice.get("prompt") or "Select option...", 100),
                    custom_id=f"sm:lp:choice:{sid}:{self.allowed_user_id}",
                    options=[
                        discord.SelectOption(label=_trunc(o["label"], 100), value=_trunc(o["value"], 100))
                        for o in slice_opts
                    ],
                )
                self.add_item(sel)
                if total_pages > 1:
                    if cur_page > 0:
                        self.add_item(_LifepathButton(
                            label="◀ Prev",
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"sm:lp:page:{sid}:{cur_page - 1}:{self.allowed_user_id}",
                        ))
                    if cur_page + 1 < total_pages:
                        self.add_item(_LifepathButton(
                            label="Next ▶",
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"sm:lp:page:{sid}:{cur_page + 1}:{self.allowed_user_id}",
                        ))
            else:
                self.add_item(_LifepathButton(
                    label="⌨️ Enter Choice",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"sm:lp:cmodal:{sid}:{self.allowed_user_id}",
                ))
            if active_choice.get("allow_roll") and choice_options:
                self.add_item(_LifepathButton(
                    label="🎲 Roll Randomly",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"sm:lp:cauto:{sid}:{self.allowed_user_id}",
                ))
            if active_choice.get("kind") in ("replace_skill", "exchange_60_for_skill"):
                self.add_item(_LifepathButton(
                    label="Keep Existing",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"sm:lp:ckeep:{sid}:{self.allowed_user_id}",
                ))
            if can_reroll:
                self.add_item(_LifepathButton(
                    label=f"⚡ Flex Reroll ({state.get('flex_rerolls_remaining', 0)})",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"sm:lp:reroll:{sid}:{self.allowed_user_id}",
                ))
            return

        # --- Case 2: Step 13 campaign picker (no active table yet) ---
        if step_num == 13 and table is None and not pending_sub:
            self.add_item(_LifepathButton(
                label="🎲 Firewall Event",
                style=discord.ButtonStyle.primary,
                custom_id=f"sm:lp:camp:{sid}:firewall-event:{self.allowed_user_id}",
            ))
            self.add_item(_LifepathButton(
                label="🎲 Gatecrashing Event",
                style=discord.ButtonStyle.primary,
                custom_id=f"sm:lp:camp:{sid}:gatecrashing-event:{self.allowed_user_id}",
            ))
            self.add_item(_LifepathButton(
                label="🎲 Crime Event",
                style=discord.ButtonStyle.primary,
                custom_id=f"sm:lp:camp:{sid}:crime-event:{self.allowed_user_id}",
            ))
            self.add_item(_LifepathButton(
                label="⏭️ Skip Step 13",
                style=discord.ButtonStyle.secondary,
                custom_id=f"sm:lp:skip:{sid}:{self.allowed_user_id}",
            ))
            if can_reroll:
                self.add_item(_LifepathButton(
                    label=f"⚡ Flex Reroll ({state.get('flex_rerolls_remaining', 0)})",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"sm:lp:reroll:{sid}:{self.allowed_user_id}",
                ))
            return

        # --- Case 3: Step 15 Finalize & Gear Packs ---
        if step_num >= 15 and not pending_sub:
            camp_packs: list[LifepathEntry] = ctx["camp_packs"]
            prof_packs: list[LifepathEntry] = ctx["prof_packs"]
            if camp_packs:
                self.add_item(_LifepathSelect(
                    placeholder=_trunc(f"Campaign Gear Pack ({sheet['gear_pack_campaign'] or 'Choose'})", 100),
                    custom_id=f"sm:lp:gcamp:{sid}:{self.allowed_user_id}",
                    options=[
                        discord.SelectOption(
                            label=_trunc(e.title, 100),
                            value=_trunc(e.title, 100),
                            default=(e.title == sheet["gear_pack_campaign"]),
                        )
                        for e in camp_packs[:SELECT_PAGE_SIZE]
                    ],
                ))
            if prof_packs:
                rec_prof = CAREER_TO_GEAR_PACK.get(state.get("career_group", ""), "")
                self.add_item(_LifepathSelect(
                    placeholder=_trunc(f"Profession Gear Pack ({sheet['gear_pack_profession'] or rec_prof or 'Choose'})", 100),
                    custom_id=f"sm:lp:gprof:{sid}:{self.allowed_user_id}",
                    options=[
                        discord.SelectOption(
                            label=_trunc(f"{e.title}{' (Recommended)' if e.title == rec_prof else ''}", 100),
                            value=_trunc(e.title, 100),
                            default=(e.title == sheet["gear_pack_profession"]),
                        )
                        for e in prof_packs[:SELECT_PAGE_SIZE]
                    ],
                ))
            mot_pool = sheet["motivations_pool"]
            if mot_pool:
                unique_mots = list(dict.fromkeys(mot_pool))[:SELECT_PAGE_SIZE]
                self.add_item(_LifepathSelect(
                    placeholder="Pick up to 3 Motivations",
                    custom_id=f"sm:lp:mots:{sid}:{self.allowed_user_id}",
                    min_values=1,
                    max_values=min(3, len(unique_mots)),
                    options=[
                        discord.SelectOption(
                            label=_trunc(m, 100),
                            value=_trunc(m, 100),
                            default=(m in sheet["motivations"]),
                        )
                        for m in unique_mots
                    ],
                ))
            if can_reroll:
                self.add_item(_LifepathButton(
                    label=f"⚡ Flex Reroll ({state.get('flex_rerolls_remaining', 0)})",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"sm:lp:reroll:{sid}:{self.allowed_user_id}",
                ))
            if sheet["skill_overflows"] or sheet["rep_overflows"]:
                self.add_item(_LifepathButton(
                    label="⚖️ Reassign >80 Overflow",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"sm:lp:ovflow:{sid}:{self.allowed_user_id}",
                ))
            self.add_item(_LifepathButton(
                label="✅ Finalize & Save",
                style=discord.ButtonStyle.success,
                custom_id=f"sm:lp:save:{sid}:{self.allowed_user_id}",
            ))
            self.add_item(_LifepathButton(
                label="📄 Export Sheet (.md)",
                style=discord.ButtonStyle.secondary,
                custom_id=f"sm:lp:md:{sid}:{self.allowed_user_id}",
            ))
            return

        # --- Case 4: Standard active table (or Step 14 optional / pending sub-roll) ---
        if table is not None:
            # Optional direct choose dropdown if allow_choice and not a pending random-only sub-roll
            choosable = [
                e for e in table_entries
                if not ((e.effects or {}).get("flags") or {}).get("reroll_sub")
            ]
            if table.allow_choice and not pending_sub and choosable:
                total_pages = max(1, (len(choosable) + SELECT_PAGE_SIZE - 1) // SELECT_PAGE_SIZE)
                cur_page = min(self.page, total_pages - 1)
                slice_entries = choosable[cur_page * SELECT_PAGE_SIZE : (cur_page + 1) * SELECT_PAGE_SIZE]
                self.add_item(_LifepathSelect(
                    placeholder=_trunc(f"Choose from {table.name} (or click Roll)...", 100),
                    custom_id=f"sm:lp:pick:{sid}:{table.slug}:{self.allowed_user_id}",
                    options=[
                        discord.SelectOption(
                            label=_trunc(f"[{e.roll_display}] {e.title}", 100),
                            value=e.code,
                            description=_trunc(e.summary, 100) if e.summary else None,
                        )
                        for e in slice_entries
                    ],
                ))
                if total_pages > 1:
                    if cur_page > 0:
                        self.add_item(_LifepathButton(
                            label="◀ Prev",
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"sm:lp:page:{sid}:{cur_page - 1}:{self.allowed_user_id}",
                        ))
                    if cur_page + 1 < total_pages:
                        self.add_item(_LifepathButton(
                            label="Next ▶",
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"sm:lp:page:{sid}:{cur_page + 1}:{self.allowed_user_id}",
                        ))

            roll_btn_label = f"🎲 Roll {table.name}" if len(table.name) <= 32 else "🎲 Roll Table"
            self.add_item(_LifepathButton(
                label=_trunc(roll_btn_label, 80),
                style=discord.ButtonStyle.primary,
                custom_id=f"sm:lp:roll:{sid}:{table.slug}:{self.allowed_user_id}",
            ))
            if step_num == 14 and not pending_sub:
                self.add_item(_LifepathButton(
                    label="⏭️ Skip Story Event",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"sm:lp:skip:{sid}:{self.allowed_user_id}",
                ))
            if can_reroll:
                self.add_item(_LifepathButton(
                    label=f"⚡ Flex Reroll ({state.get('flex_rerolls_remaining', 0)})",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"sm:lp:reroll:{sid}:{self.allowed_user_id}",
                ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from spacemarches.management.commands.run_discord_bot import _claim_interaction
        _claim_interaction(getattr(interaction, "id", None))
        if str(interaction.user.id) != self.allowed_user_id:
            await interaction.response.send_message(
                "This Life Path walkthrough belongs to another player. Run `/lifepath start` to roll your own character.",
                ephemeral=True,
            )
            return False
        return True


# ---------------------------------------------------------------------------
# Stateless sm:lp:* Component Dispatcher
# ---------------------------------------------------------------------------


async def handle_lifepath_component_interaction(
    interaction: discord.Interaction,
    *,
    custom_id: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Handle all sm:lp:* button and select interactions (both live and after bot restart)."""
    if not custom_id.startswith("sm:lp:"):
        return False

    parts = custom_id.split(":")
    action = parts[2] if len(parts) > 2 else ""
    try:
        session_id = int(parts[3])
    except (IndexError, ValueError):
        return False
    allowed_uid = parts[-1] if len(parts) >= 5 else ""

    if allowed_uid and str(interaction.user.id) != str(allowed_uid):
        await interaction.response.send_message(
            "This Life Path walkthrough belongs to another player.",
            ephemeral=True,
        )
        return True

    values = (data or {}).get("values") or []

    try:
        if action == "roll":
            table_slug = parts[4] if len(parts) >= 6 else None
            await _perform_roll_async(session_id, table_slug=table_slug)
        elif action == "pick":
            table_slug = parts[4] if len(parts) >= 6 else None
            chosen_code = str(values[0]) if values else None
            await _perform_roll_async(session_id, table_slug=table_slug, chosen_entry_code=chosen_code)
        elif action == "camp":
            table_slug = parts[4] if len(parts) >= 6 else "firewall-event"
            await _perform_roll_async(session_id, table_slug=table_slug)
        elif action == "reroll":
            await _reroll_flex_async(session_id)
        elif action == "choice":
            picked = str(values[0]) if values else ""
            await _resolve_choice_async(session_id, selected_value=picked)
        elif action == "cauto":
            await _resolve_choice_async(session_id, auto_roll=True)
        elif action == "ckeep":
            await _resolve_choice_async(session_id, selected_value="keep")
        elif action == "cmodal":
            ctx = await _get_render_context_async(session_id)
            prompt = (ctx["active_choice"] or {}).get("prompt", "Enter value")
            await interaction.response.send_modal(
                CustomTextChoiceModal(session_id=session_id, prompt=prompt, allowed_user_id=allowed_uid)
            )
            return True
        elif action == "skip":
            await _skip_step_async(session_id)
        elif action == "page":
            new_page = int(parts[4]) if len(parts) >= 6 else 0
            ctx = await _get_render_context_async(session_id)
            await interaction.response.edit_message(
                embed=build_lifepath_embed(ctx),
                view=LifepathHubView(ctx, allowed_user_id=allowed_uid, page=new_page),
            )
            return True
        elif action == "gcamp":
            await _apply_step15_packs_async(session_id, campaign_pack=str(values[0]) if values else None)
        elif action == "gprof":
            await _apply_step15_packs_async(session_id, profession_pack=str(values[0]) if values else None)
        elif action == "mots":
            await _apply_step15_packs_async(session_id, motivations=[str(v) for v in values])
        elif action == "ovflow":
            ctx = await _get_render_context_async(session_id)
            sheet = ctx["sheet"]
            first_ov = (sheet["skill_overflows"] or [None])[0] or (sheet["rep_overflows"] or [None])[0]
            if not first_ov:
                await interaction.response.send_message("No stats exceed the 80 cap.", ephemeral=True)
                return True
            src_name = first_ov.get("skill") or first_ov.get("rep")
            await interaction.response.send_modal(
                ReallocateOverflowModal(
                    session_id=session_id,
                    source_name=src_name,
                    excess=int(first_ov["excess"]),
                    allowed_user_id=allowed_uid,
                )
            )
            return True
        elif action == "save":
            ctx = await _get_render_context_async(session_id)
            await interaction.response.send_modal(
                FinalizeNameModal(
                    session_id=session_id,
                    current_name=ctx["sheet"]["character_name"],
                    allowed_user_id=allowed_uid,
                )
            )
            return True
        elif action == "md":
            cname, md_text = await _render_markdown_async(session_id)
            buf = io.BytesIO(md_text.encode("utf-8"))
            fname = f"{cname.lower().replace(' ', '-') or 'lifepath'}-sheet.md"
            await interaction.response.send_message(
                content=f"Exported Life Path sheet for **{cname}**:",
                file=discord.File(buf, filename=fname),
                ephemeral=True,
            )
            return True
        else:
            return False
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return True

    ctx = await _get_render_context_async(session_id)
    await interaction.response.edit_message(
        embed=build_lifepath_embed(ctx),
        view=LifepathHubView(ctx, allowed_user_id=allowed_uid),
    )
    return True


# ---------------------------------------------------------------------------
# Slash Command Handlers (/lifepath start, resume, roll, choose, reroll, summary, save)
# ---------------------------------------------------------------------------


async def handle_lifepath_start_command(
    interaction: discord.Interaction,
    *,
    character_name: str | None = None,
    hardcore_flex: bool = False,
    target_channel: Any = None,
) -> None:
    channel_id = str(getattr(getattr(interaction, "channel", None), "id", "") or "")
    session = await _start_session_async(
        discord_user_id=str(interaction.user.id),
        character_name=(character_name or "").strip() or f"{getattr(interaction.user, 'display_name', 'Agent')} Ego",
        channel_id=channel_id,
        hardcore_flex=hardcore_flex,
    )
    ctx = await _get_render_context_async(session.pk)
    embed = build_lifepath_embed(ctx)
    view = LifepathHubView(ctx, allowed_user_id=str(interaction.user.id))
    if target_channel is not None:
        from spacemarches.management.commands.run_discord_bot import _post_to_target_channel
        mention = getattr(interaction.user, "mention", "")
        content = f"{mention} — EP2e Life Path session started:" if isinstance(mention, str) and mention else ""
        ok, dest_info = await _post_to_target_channel(target_channel, content=content, embed=embed, view=view)
        if not ok:
            await interaction.response.send_message(dest_info, ephemeral=True)
            return
        await interaction.response.send_message(f"Started Life Path in {dest_info}.", ephemeral=True)
        return
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


async def handle_lifepath_resume_command(interaction: discord.Interaction) -> None:
    session = await _get_session_async(discord_user_id=str(interaction.user.id), include_completed=True)
    if session is None:
        await interaction.response.send_message(
            "You have no Life Path session yet. Run `/lifepath start` to begin!",
            ephemeral=True,
        )
        return
    ctx = await _get_render_context_async(session.pk)
    await interaction.response.send_message(
        embed=build_lifepath_embed(ctx),
        view=LifepathHubView(ctx, allowed_user_id=str(interaction.user.id)),
        ephemeral=False,
    )


async def handle_lifepath_roll_command(
    interaction: discord.Interaction,
    *,
    campaign_table: str | None = None,
) -> None:
    session = await _get_session_async(discord_user_id=str(interaction.user.id), include_completed=False)
    if session is None:
        await interaction.response.send_message(
            "No active Life Path session found. Run `/lifepath start` first.",
            ephemeral=True,
        )
        return
    try:
        await _perform_roll_async(session.pk, table_slug=campaign_table)
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return
    ctx = await _get_render_context_async(session.pk)
    await interaction.response.send_message(
        embed=build_lifepath_embed(ctx),
        view=LifepathHubView(ctx, allowed_user_id=str(interaction.user.id)),
        ephemeral=False,
    )


async def handle_lifepath_choose_command(
    interaction: discord.Interaction,
    *,
    option: str,
) -> None:
    session = await _get_session_async(discord_user_id=str(interaction.user.id), include_completed=False)
    if session is None:
        await interaction.response.send_message(
            "No active Life Path session found. Run `/lifepath start` first.",
            ephemeral=True,
        )
        return
    ctx_before = await _get_render_context_async(session.pk)
    try:
        if ctx_before["active_choice"]:
            await _resolve_choice_async(session.pk, selected_value=option)
        else:
            table = ctx_before["table"]
            if table is None:
                raise ValueError("No selectable table is active right now.")
            # Match by entry code or title
            entries = ctx_before["table_entries"]
            match = next(
                (e for e in entries if e.code == option or e.title.lower() == option.strip().lower()),
                None,
            )
            if match is None:
                raise ValueError(f"Option '{option}' not found in {table.name}.")
            await _perform_roll_async(session.pk, table_slug=table.slug, chosen_entry_code=match.code)
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return
    ctx = await _get_render_context_async(session.pk)
    await interaction.response.send_message(
        embed=build_lifepath_embed(ctx),
        view=LifepathHubView(ctx, allowed_user_id=str(interaction.user.id)),
        ephemeral=False,
    )


async def handle_lifepath_reroll_command(interaction: discord.Interaction) -> None:
    session = await _get_session_async(discord_user_id=str(interaction.user.id), include_completed=False)
    if session is None:
        await interaction.response.send_message(
            "No active Life Path session found. Run `/lifepath start` first.",
            ephemeral=True,
        )
        return
    try:
        await _reroll_flex_async(session.pk)
    except ValueError as err:
        await interaction.response.send_message(str(err), ephemeral=True)
        return
    ctx = await _get_render_context_async(session.pk)
    await interaction.response.send_message(
        content="⚡ **Spent 1 Ego Flex to reroll!**",
        embed=build_lifepath_embed(ctx),
        view=LifepathHubView(ctx, allowed_user_id=str(interaction.user.id)),
        ephemeral=False,
    )


async def handle_lifepath_summary_command(interaction: discord.Interaction) -> None:
    session = await _get_session_async(discord_user_id=str(interaction.user.id), include_completed=True)
    if session is None:
        await interaction.response.send_message(
            "No Life Path session found. Run `/lifepath start` first.",
            ephemeral=True,
        )
        return
    cname, md_text = await _render_markdown_async(session.pk)
    buf = io.BytesIO(md_text.encode("utf-8"))
    fname = f"{cname.lower().replace(' ', '-') or 'lifepath'}-sheet.md"
    ctx = await _get_render_context_async(session.pk)
    await interaction.response.send_message(
        embed=build_lifepath_embed(ctx),
        file=discord.File(buf, filename=fname),
        ephemeral=False,
    )


async def handle_lifepath_save_command(
    interaction: discord.Interaction,
    *,
    character_name: str | None = None,
    create_dossier: bool = False,
) -> None:
    session = await _get_session_async(discord_user_id=str(interaction.user.id), include_completed=True)
    if session is None:
        await interaction.response.send_message(
            "No Life Path session found. Run `/lifepath start` first.",
            ephemeral=True,
        )
        return
    session, gen_char = await _finalize_session_async(
        session.pk,
        discord_user_id=str(interaction.user.id),
        character_name=character_name,
        create_dossier=create_dossier,
    )
    ctx = await _get_render_context_async(session.pk)
    note = (
        f"Saved **{session.character_name}** to your Spacemarches Character Roster (Sheet `#{gen_char.pk}`)."
        if gen_char
        else f"Completed **{session.character_name}**! Run `/link <code>` and re-run `/lifepath save` to store on your web account."
    )
    await interaction.response.send_message(
        content=note,
        embed=build_lifepath_embed(ctx),
        view=LifepathHubView(ctx, allowed_user_id=str(interaction.user.id)),
        ephemeral=False,
    )
