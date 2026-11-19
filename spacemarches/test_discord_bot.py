from io import StringIO
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from asgiref.sync import async_to_sync
import discord
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from spacemarches.management.commands.run_discord_bot import (
    CharacterSelect,
    CreateDossierButton,
    CreateDossierModal,
    DebriefQuestionButton,
    DossierAnswerModal,
    DossierEditButton,
    DossierQuestionSelect,
    LaunchIntakeButton,
    OnboardingInviteView,
    SendTargetIntakeButton,
    build_bot,
    handle_debrief_command,
    handle_dossier_command,
    handle_dossier_create_command,
    handle_dossier_list_command,
    handle_dossier_open_command,
    handle_dossier_swap_command,
    handle_intake_command,
    handle_link_command,
)
from spacemarches.models import CharacterDossier, DiscordIntakeInvite, DiscordLink
from spacemarches.questionnaire import get_question
from spacemarches.services.dossier_service import generate_discord_link_code, save_dossier_answer

User = get_user_model()


def _mock_interaction(discord_user_id: str, *, channel=None):
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = discord_user_id
    interaction.user.display_name = "TestAgent"
    interaction.channel = channel
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    return interaction


def _mock_member_interaction(
    discord_user_id: str,
    *,
    manage_guild: bool = False,
    role_names: list[str] | None = None,
    display_name: str = "MemberAgent",
    channel=None,
):
    interaction = _mock_interaction(discord_user_id, channel=channel)
    member = MagicMock(spec=discord.Member)
    member.id = discord_user_id
    member.display_name = display_name
    member.mention = f"<@{discord_user_id}>"
    member.guild_permissions = discord.Permissions(manage_guild=manage_guild)
    roles = []
    for rname in role_names or []:
        role = MagicMock()
        role.name = rname
        roles.append(role)
    member.roles = roles
    member.send = AsyncMock()
    interaction.user = member
    return interaction


class DiscordBotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="discord-player")
        self.dossier = CharacterDossier.objects.create(
            user=self.user,
            character_name="Echo Seven",
            slug="echo-seven",
        )

    def test_management_command_help_runs(self):
        out = StringIO()
        with self.assertRaises(SystemExit) as ctx:
            call_command("run_discord_bot", "--help", stdout=out)
        self.assertEqual(ctx.exception.code, 0)

    def test_build_bot_registers_dossier_group_and_intake(self):
        client = build_bot()
        cmd_names = {cmd.name for cmd in client.tree.get_commands()}
        self.assertIn("link", cmd_names)
        self.assertIn("dossier", cmd_names)
        self.assertIn("intake", cmd_names)
        self.assertIn("debrief", cmd_names)

        dossier_group = next(cmd for cmd in client.tree.get_commands() if cmd.name == "dossier")
        sub_names = {sub.name for sub in dossier_group.commands}
        self.assertEqual(sub_names, {"open", "swap", "list", "create"})

        intake_cmd = next(cmd for cmd in client.tree.get_commands() if cmd.name == "intake")
        cat_param = next(p for p in intake_cmd.parameters if p.name == "category")
        self.assertGreaterEqual(len(cat_param.choices), 20)
        self.assertIn("Campaign Hooks", [c.value for c in cat_param.choices])

    def test_slash_link_and_intake_and_modal_save(self):
        code = generate_discord_link_code(self.user)
        interaction = _mock_interaction("555000111")

        async_to_sync(handle_link_command)(interaction, code)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.call_args.kwargs.get("ephemeral"))

        link = DiscordLink.objects.get(user=self.user)
        self.assertEqual(link.discord_user_id, "555000111")

        # Seed an answer on web, then test /intake (and /dossier alias) ephemeral embed + view
        save_dossier_answer(
            self.dossier,
            "15a",
            "Investigating Pandora Gate 4",
            entry_kind="character_creation",
            stardate_era="pre_fall",
            source="web",
        )
        dossier_interaction = _mock_interaction("555000111")
        async_to_sync(handle_dossier_command)(dossier_interaction, category="Campaign Hooks")
        dossier_interaction.response.send_message.assert_awaited_once()
        kwargs = dossier_interaction.response.send_message.call_args.kwargs
        self.assertTrue(kwargs.get("ephemeral"))
        self.assertIn("Echo Seven", kwargs["embed"].title)

        # Simulate submitting a Discord Modal edit with a Post-Fall Sol-date
        async def _submit_modal():
            q = get_question("15a")
            modal = DossierAnswerModal(
                dossier_id=self.dossier.pk,
                question=q,
                current_answer="Investigating Pandora Gate 4",
                sol_date="3.750",
            )
            modal.stardate_input._value = "3.750"
            modal.answer_input._value = "Gate 4 was sabotaged from inside."
            modal_interaction = _mock_interaction("555000111")
            await modal.on_submit(modal_interaction)
            modal_interaction.response.send_message.assert_awaited_once()
            self.assertTrue(modal_interaction.response.send_message.call_args.kwargs.get("ephemeral"))

        async_to_sync(_submit_modal)()
        self.dossier.refresh_from_db()
        entry = self.dossier.responses["15a"]
        self.assertEqual(entry["answer"], "Gate 4 was sabotaged from inside.")
        self.assertEqual(entry["source"], "discord")
        self.assertEqual(entry["version_label"], "Sol 3.750_v1")
        self.assertEqual(len(entry["revisions"]), 1)

        # Verify select formatting avoids collapsing [ ] and renders full unclipped prompt on selection
        async def _select_and_open_modal():
            q_long = get_question("1")
            view = kwargs["view"]
            select = next(item for item in view.children if isinstance(item, DossierQuestionSelect))
            for opt in select.options:
                self.assertNotIn("[ ]", opt.label)
                self.assertRegex(opt.label, r"^(?:✓|○) \[[^\]]+\] ")

            q1_select = DossierQuestionSelect(dossier=self.dossier, questions=[q_long])
            select_interaction = _mock_interaction("555000111")
            with patch.object(DossierQuestionSelect, "values", new_callable=PropertyMock, return_value=["1"]):
                await q1_select.callback(select_interaction)
            select_interaction.response.edit_message.assert_awaited_once()
            edit_kwargs = select_interaction.response.edit_message.call_args.kwargs
            self.assertIn(q_long["prompt"], edit_kwargs["embed"].description)
            self.assertIn(q_long["lore_text"], edit_kwargs["embed"].description)

            edit_btn = next(item for item in edit_kwargs["view"].children if isinstance(item, DossierEditButton))
            btn_interaction = _mock_interaction("555000111")
            await edit_btn.callback(btn_interaction)
            btn_interaction.response.send_modal.assert_awaited_once()
            opened_modal = btn_interaction.response.send_modal.call_args.args[0]
            self.assertEqual(opened_modal.answer_input.label, "Response for [1]")

        async_to_sync(_select_and_open_modal)()

    def test_dossier_create_swap_list_open_and_intake_flow(self):
        DiscordLink.objects.create(user=self.user, discord_user_id="666000222")

        # 1. /dossier create opens CreateDossierModal and creates + activates second character
        create_interaction = _mock_interaction("666000222")
        async_to_sync(handle_dossier_create_command)(create_interaction)
        create_interaction.response.send_modal.assert_awaited_once()

        async def _create_second_character():
            modal = CreateDossierModal()
            modal.character_name_input._value = "Dr. Elena Vance"
            modal.narrative_voice_input._value = "omniscient"
            submit_interaction = _mock_interaction("666000222")
            await modal.on_submit(submit_interaction)
            submit_interaction.response.send_message.assert_awaited_once()
            kwargs = submit_interaction.response.send_message.call_args.kwargs
            self.assertTrue(kwargs.get("ephemeral"))
            self.assertIn("Dr. Elena Vance", kwargs["embed"].title)

        async_to_sync(_create_second_character)()
        vance = CharacterDossier.objects.get(user=self.user, slug="dr-elena-vance")
        self.assertEqual(vance.narrative_voice, CharacterDossier.VOICE_OMNISCIENT)
        link = DiscordLink.objects.get(user=self.user)
        self.assertEqual(link.active_dossier_id, vance.pk)

        # 2. /dossier list shows both characters with Vance active
        list_interaction = _mock_interaction("666000222")
        async_to_sync(handle_dossier_list_command)(list_interaction)
        list_kwargs = list_interaction.response.send_message.call_args.kwargs
        self.assertIn("**[ACTIVE]** **Dr. Elena Vance**", list_kwargs["embed"].description)
        self.assertIn("Echo Seven", list_kwargs["embed"].description)

        # 3. /dossier swap switches active character back to Echo Seven
        swap_interaction = _mock_interaction("666000222")
        async_to_sync(handle_dossier_swap_command)(swap_interaction, "echo-seven")
        link.refresh_from_db()
        self.assertEqual(link.active_dossier_id, self.dossier.pk)
        swap_kwargs = swap_interaction.response.send_message.call_args.kwargs
        self.assertIn("Echo Seven", swap_kwargs["embed"].title)

        # 4. Dropdown CharacterSelect swaps back to Dr. Elena Vance in place via edit_message
        async def _dropdown_swap_and_launch_intake():
            open_interaction = _mock_interaction("666000222")
            await handle_dossier_open_command(open_interaction)
            open_kwargs = open_interaction.response.send_message.call_args.kwargs
            char_select = next(item for item in open_kwargs["view"].children if isinstance(item, CharacterSelect))

            sel_interaction = _mock_interaction("666000222")
            with patch.object(CharacterSelect, "values", new_callable=PropertyMock, return_value=[str(vance.pk)]):
                await char_select.callback(sel_interaction)
            sel_interaction.response.edit_message.assert_awaited_once()
            sel_kwargs = sel_interaction.response.edit_message.call_args.kwargs
            self.assertIn("Dr. Elena Vance", sel_kwargs["embed"].title)

            # Launch /intake right from the dossier hub button
            intake_btn = next(item for item in sel_kwargs["view"].children if isinstance(item, LaunchIntakeButton))
            btn_interaction = _mock_interaction("666000222")
            await intake_btn.callback(btn_interaction)
            btn_interaction.response.edit_message.assert_awaited_once()
            intake_kwargs = btn_interaction.response.edit_message.call_args.kwargs
            self.assertIn("Intake: Dr. Elena Vance", intake_kwargs["embed"].title)
            q_select = next(item for item in intake_kwargs["view"].children if isinstance(item, DossierQuestionSelect))
            self.assertEqual(len(q_select.options), 16)  # Default Core-first intake

        async_to_sync(_dropdown_swap_and_launch_intake)()
        link.refresh_from_db()
        self.assertEqual(link.active_dossier_id, vance.pk)

        # 5. /intake when user has 0 dossiers offers CreateDossierButton
        other_user = User.objects.create_user(username="fresh-player")
        DiscordLink.objects.create(user=other_user, discord_user_id="888000333")
        empty_intake = _mock_interaction("888000333")
        async_to_sync(handle_intake_command)(empty_intake)
        empty_kwargs = empty_intake.response.send_message.call_args.kwargs
        self.assertTrue(any(isinstance(c, CreateDossierButton) for c in empty_kwargs["view"].children))

    def test_slash_debrief_dms_player_interactive_buttons(self):
        DiscordLink.objects.create(user=self.user, discord_user_id="777888999")
        gm_interaction = _mock_interaction("999000111")
        member = MagicMock()
        member.id = "777888999"
        member.display_name = "EchoPlayer"
        member.send = AsyncMock()

        async_to_sync(handle_debrief_command)(
            gm_interaction,
            member=member,
            stardate="5.125",
            question_ids="15a,15b,6.1d",
        )
        member.send.assert_awaited_once()
        dm_kwargs = member.send.call_args.kwargs
        self.assertIn("Sol 5.125", dm_kwargs["embed"].title)
        self.assertEqual(len(dm_kwargs["view"].children), 3)
        gm_interaction.response.send_message.assert_awaited_once()
        self.assertTrue(gm_interaction.response.send_message.call_args.kwargs.get("ephemeral"))

    def test_unlinked_intake_onboarding_dm_channel_fallback_and_claim_on_link(self):
        # 1. Cold unlinked non-ST member is rejected on self /intake, /dossier open, and targeting another member
        cold_interaction = _mock_member_interaction("333444555", manage_guild=False, display_name="NewPlayer")
        async_to_sync(handle_intake_command)(cold_interaction)
        self.assertIn("not linked yet", cold_interaction.response.send_message.call_args.args[0])

        cold_open = _mock_member_interaction("333444555", manage_guild=False, display_name="NewPlayer")
        async_to_sync(handle_dossier_open_command)(cold_open)
        self.assertIn("not linked yet", cold_open.response.send_message.call_args.args[0])

        other_target = MagicMock(spec=discord.Member)
        other_target.id = "999888777"
        other_target.display_name = "Bystander"
        other_target.mention = "<@999888777>"
        other_target.send = AsyncMock()
        cold_target_attempt = _mock_member_interaction("333444555", manage_guild=False)
        async_to_sync(handle_intake_command)(cold_target_attempt, member=other_target)
        self.assertIn("Only linked users or Storytellers/Admins", cold_target_attempt.response.send_message.call_args.args[0])
        other_target.send.assert_not_called()

        # 2. ST member (even without website DiscordLink) prompts unlinked NewPlayer via /intake member:@NewPlayer
        st_interaction = _mock_member_interaction("111222333", role_names=["Storyteller"], display_name="GM-Ari")
        new_player = MagicMock(spec=discord.Member)
        new_player.id = "333444555"
        new_player.display_name = "NewPlayer"
        new_player.mention = "<@333444555>"
        new_player.send = AsyncMock()

        async_to_sync(handle_intake_command)(st_interaction, member=new_player)
        new_player.send.assert_awaited_once()
        invite = DiscordIntakeInvite.objects.get(discord_user_id="333444555")
        self.assertIsNotNone(invite)

        dm_kwargs = new_player.send.call_args.kwargs
        onboarding_view = dm_kwargs["view"]
        self.assertIsInstance(onboarding_view, OnboardingInviteView)

        # Wrong actor clicking the onboarding button is blocked
        bystander_click = _mock_interaction("999888777")
        btn = next(item for item in onboarding_view.children if isinstance(item, CreateDossierButton))
        async_to_sync(btn.callback)(bystander_click)
        self.assertIn("belongs to another player", bystander_click.response.send_message.call_args.args[0])

        # 3. Unlinked NewPlayer clicks Create Character & Start Intake -> creates unclaimed dossier & starts intake
        new_player_click = _mock_member_interaction("333444555", display_name="NewPlayer")
        async_to_sync(btn.callback)(new_player_click)
        new_player_click.response.send_modal.assert_awaited_once()
        opened_modal = new_player_click.response.send_modal.call_args.args[0]
        self.assertIsInstance(opened_modal, CreateDossierModal)
        self.assertTrue(opened_modal.allow_unlinked)
        self.assertTrue(opened_modal.start_intake_on_create)

        async def _submit_new_char():
            opened_modal.character_name_input._value = "Nova Drift"
            opened_modal.narrative_voice_input._value = "first"
            submit_inter = _mock_member_interaction("333444555", display_name="NewPlayer")
            await opened_modal.on_submit(submit_inter)
            submit_inter.response.send_message.assert_awaited_once()
            s_kwargs = submit_inter.response.send_message.call_args.kwargs
            self.assertIn("Created & Starting Intake: Nova Drift", s_kwargs["embed"].title)
            self.assertIn("Unclaimed Onboarding Sheet", s_kwargs["embed"].description)
            q_select = next(item for item in s_kwargs["view"].children if isinstance(item, DossierQuestionSelect))
            self.assertEqual(len(q_select.options), 16)

        async_to_sync(_submit_new_char)()
        unclaimed = CharacterDossier.objects.get(user__isnull=True, discord_owner_id="333444555")

        async def _submit_answer():
            modal = DossierAnswerModal(
                dossier_id=unclaimed.pk,
                question=get_question("1"),
                sol_date="10.000",
            )
            modal.stardate_input._value = "10.000"
            modal.answer_input._value = "Nova Drift // Callsign Relay"
            ans_inter = _mock_member_interaction("333444555", display_name="NewPlayer")
            await modal.on_submit(ans_inter)
            ans_inter.response.send_message.assert_awaited_once()

        async_to_sync(_submit_answer)()

        # 4. Unlinked player can run /dossier list and ST can run /debrief against unclaimed dossier
        list_inter = _mock_member_interaction("333444555", display_name="NewPlayer")
        async_to_sync(handle_dossier_list_command)(list_inter)
        self.assertIn("Unclaimed", list_inter.response.send_message.call_args.kwargs["embed"].description)

        new_player.send.reset_mock()
        async_to_sync(handle_debrief_command)(
            st_interaction,
            member=new_player,
            stardate="10.250",
            question_ids="1",
        )
        new_player.send.assert_awaited_once()
        self.assertIn("Nova Drift", new_player.send.call_args.kwargs["embed"].description)

        # 5. Later, player makes a website account and runs /link <code> -> claims Nova Drift automatically
        late_user = User.objects.create_user(username="late-joiner")
        link_code = generate_discord_link_code(late_user)
        link_inter = _mock_member_interaction("333444555", display_name="NewPlayer")
        async_to_sync(handle_link_command)(link_inter, link_code)
        reply_msg = link_inter.response.send_message.call_args.args[0]
        self.assertIn("Nova Drift", reply_msg)
        self.assertIn("Claimed 1 onboarded character dossier(s)", reply_msg)

        claimed = CharacterDossier.objects.get(character_name="Nova Drift")
        self.assertEqual(claimed.user, late_user)
        self.assertFalse(DiscordIntakeInvite.objects.filter(discord_user_id="333444555").exists())

        # 6. DM Forbidden falls back to channel post when channel.send is async, and explicit delivery='channel' works
        DiscordLink.objects.create(user=self.user, discord_user_id="222111000")
        linked_invoker = _mock_member_interaction("222111000", manage_guild=False, display_name="LinkedFriend")
        channel_mock = MagicMock()
        channel_mock.send = AsyncMock()
        linked_invoker.channel = channel_mock

        closed_dm_target = MagicMock(spec=discord.Member)
        closed_dm_target.id = "444555666"
        closed_dm_target.display_name = "ClosedDMs"
        closed_dm_target.mention = "<@444555666>"
        closed_dm_target.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Cannot send messages"))

        async_to_sync(handle_intake_command)(linked_invoker, member=closed_dm_target)
        channel_mock.send.assert_awaited_once()
        self.assertIn("DMs are closed", channel_mock.send.call_args.kwargs["content"])
        self.assertIn("instead", linked_invoker.response.send_message.call_args.args[0])

    def test_st_creates_named_character_for_target_via_intake_and_dossier_create(self):
        st_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
        target = MagicMock(spec=discord.Member)
        target.id = "900800700"
        target.display_name = "FreshAgent"
        target.mention = "<@900800700>"
        target.send = AsyncMock()

        # 1. /intake member:@FreshAgent character:"Vesper Callsign" initializes the character on FreshAgent
        async_to_sync(handle_intake_command)(
            st_inter,
            member=target,
            character="Vesper Callsign",
        )
        vesper = CharacterDossier.objects.get(
            user__isnull=True,
            discord_owner_id="900800700",
            character_name="Vesper Callsign",
        )
        self.assertFalse(CharacterDossier.objects.filter(discord_owner_id="100200300").exists())
        target.send.assert_awaited_once()
        dm_kwargs = target.send.call_args.kwargs
        self.assertIn("Intake: Vesper Callsign", dm_kwargs["embed"].title)
        self.assertIn("initialized", st_inter.response.send_message.call_args.args[0])

        # 2. Unlinked non-ST cannot /dossier create for another member
        cold_caller = _mock_member_interaction("777666555", manage_guild=False)
        async_to_sync(handle_dossier_create_command)(cold_caller, member=target)
        self.assertIn("Only linked users or Storytellers/Admins", cold_caller.response.send_message.call_args.args[0])

        # 3. ST runs /dossier create member:@FreshAgent -> creates Backup Ego for FreshAgent (not ST)
        create_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
        async_to_sync(handle_dossier_create_command)(create_inter, member=target)
        create_inter.response.send_modal.assert_awaited_once()
        modal = create_inter.response.send_modal.call_args.args[0]
        self.assertEqual(modal.target_discord_user_id, "900800700")

        async def _submit_target_modal():
            modal.character_name_input._value = "Backup Ego"
            modal.narrative_voice_input._value = "omniscient"
            sub_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
            await modal.on_submit(sub_inter)
            sub_inter.response.send_message.assert_awaited_once()
            s_kwargs = sub_inter.response.send_message.call_args.kwargs
            self.assertIn("Initialized for FreshAgent: Backup Ego", s_kwargs["embed"].title)
            send_btn = next(c for c in s_kwargs["view"].children if isinstance(c, SendTargetIntakeButton))
            target.send.reset_mock()
            btn_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
            await send_btn.callback(btn_inter)
            target.send.assert_awaited_once()
            self.assertIn("Intake: Backup Ego", target.send.call_args.kwargs["embed"].title)

        async_to_sync(_submit_target_modal)()
        backup = CharacterDossier.objects.get(
            user__isnull=True,
            discord_owner_id="900800700",
            character_name="Backup Ego",
        )
        self.assertEqual(backup.narrative_voice, CharacterDossier.VOICE_OMNISCIENT)

        # 4. ST runs /dossier list member:@FreshAgent -> sees both Vesper Callsign and Backup Ego
        list_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
        async_to_sync(handle_dossier_list_command)(list_inter, member=target)
        list_embed = list_inter.response.send_message.call_args.kwargs["embed"]
        self.assertIn("FreshAgent's Character Dossiers (2)", list_embed.title)
        self.assertIn(vesper.character_name, list_embed.description)
        self.assertIn(backup.character_name, list_embed.description)

    def test_debrief_channel_fallback_button_guard_and_dossier_open_swap_member(self):
        # 1. ST creates two characters on unclaimed player 901202303
        st_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
        target = MagicMock(spec=discord.Member)
        target.id = "901202303"
        target.display_name = "ClosedAgent"
        target.mention = "<@901202303>"
        target.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "DMs disabled"))

        channel_mock = MagicMock()
        channel_mock.send = AsyncMock()
        st_inter.channel = channel_mock

        async_to_sync(handle_intake_command)(st_inter, member=target, character="Alpha Frame")
        # Channel fallback on Forbidden DM should have fired during intake
        channel_mock.send.assert_awaited_once()
        self.assertIn("DMs are closed", channel_mock.send.call_args.kwargs["content"])

        from spacemarches.services.dossier_service import create_character_dossier_for_discord

        beta = create_character_dossier_for_discord(
            "901202303",
            "Beta Frame",
            allow_unlinked=True,
        )

        # 2. Non-ST / unlinked cannot /dossier open or /dossier swap another member
        cold_caller = _mock_member_interaction("777666555", manage_guild=False)
        async_to_sync(handle_dossier_open_command)(cold_caller, member=target)
        self.assertIn("Only linked users or Storytellers/Admins", cold_caller.response.send_message.call_args.args[0])

        cold_swap = _mock_member_interaction("777666555", manage_guild=False)
        async_to_sync(handle_dossier_swap_command)(cold_swap, character="alpha-frame", member=target)
        self.assertIn("Only linked users or Storytellers/Admins", cold_swap.response.send_message.call_args.args[0])

        # 3. ST inspects target's active dossier (Beta Frame) and swaps to Alpha Frame
        open_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
        async_to_sync(handle_dossier_open_command)(open_inter, member=target)
        open_embed = open_inter.response.send_message.call_args.kwargs["embed"]
        self.assertIn("ClosedAgent's Active Dossier: Beta Frame", open_embed.title)

        swap_inter = _mock_member_interaction("100200300", role_names=["Storyteller"], display_name="ST-Valk")
        async_to_sync(handle_dossier_swap_command)(swap_inter, character="alpha-frame", member=target)
        swap_embed = swap_inter.response.send_message.call_args.kwargs["embed"]
        self.assertIn("Swapped ClosedAgent's Active Dossier: Alpha Frame", swap_embed.title)
        invite = DiscordIntakeInvite.objects.get(discord_user_id="901202303")
        self.assertNotEqual(invite.active_dossier_id, beta.pk)

        # 4. /debrief falls back to channel on Forbidden and guards buttons via allowed_user_id
        channel_mock.send.reset_mock()
        debrief_fb = _mock_member_interaction(
            "100200300",
            role_names=["Storyteller"],
            display_name="ST-Valk",
            channel=channel_mock,
        )
        async_to_sync(handle_debrief_command)(
            debrief_fb,
            member=target,
            stardate="10.500",
            question_ids="1",
            character="beta-frame",
        )
        channel_mock.send.assert_awaited_once()
        fb_kwargs = channel_mock.send.call_args.kwargs
        self.assertIn("DMs are closed", fb_kwargs["content"])
        self.assertIn("Beta Frame", fb_kwargs["embed"].description)

        debrief_btn = next(c for c in fb_kwargs["view"].children if isinstance(c, DebriefQuestionButton))
        bystander_click = _mock_member_interaction("999111222")
        async_to_sync(debrief_btn.callback)(bystander_click)
        self.assertIn("belongs to another player", bystander_click.response.send_message.call_args.args[0])

        target_click = _mock_member_interaction("901202303")
        async_to_sync(debrief_btn.callback)(target_click)
        target_click.response.send_modal.assert_awaited_once()

        # 5. Explicit delivery='channel' posts directly without calling member.send
        target.send.reset_mock()
        channel_mock.send.reset_mock()
        debrief_ch = _mock_member_interaction(
            "100200300",
            role_names=["Storyteller"],
            display_name="ST-Valk",
            channel=channel_mock,
        )
        async_to_sync(handle_debrief_command)(
            debrief_ch,
            member=target,
            stardate="10.750",
            question_ids="1",
            delivery="channel",
        )
        target.send.assert_not_called()
        channel_mock.send.assert_awaited_once()
        self.assertIn("requested a Post-Action Report", channel_mock.send.call_args.kwargs["content"])


