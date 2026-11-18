from io import StringIO
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from spacemarches.management.commands.run_discord_bot import (
    CharacterSelect,
    CreateDossierButton,
    CreateDossierModal,
    DossierAnswerModal,
    DossierEditButton,
    DossierQuestionSelect,
    LaunchIntakeButton,
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
from spacemarches.models import CharacterDossier, DiscordLink
from spacemarches.questionnaire import get_question
from spacemarches.services.dossier_service import generate_discord_link_code, save_dossier_answer

User = get_user_model()


def _mock_interaction(discord_user_id: str):
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = discord_user_id
    interaction.user.display_name = "TestAgent"
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
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
