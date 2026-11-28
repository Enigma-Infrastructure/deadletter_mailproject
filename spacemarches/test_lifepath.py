"""Tests for EP2e Life Path database models, seeding, engine mechanics, and Discord /lifepath flow."""
from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock

from asgiref.sync import async_to_sync
import discord
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from spacemarches.management.commands.run_discord_bot import (
    build_bot,
    handle_persistent_component_interaction,
)
from spacemarches.models import (
    CharacterDossier,
    DiscordLink,
    GeneratedCharacter,
    LifepathEntry,
    LifepathSession,
    LifepathTable,
)
from spacemarches.services.discord_lifepath import (
    LifepathHubView,
    handle_lifepath_choose_command,
    handle_lifepath_component_interaction,
    handle_lifepath_reroll_command,
    handle_lifepath_resume_command,
    handle_lifepath_roll_command,
    handle_lifepath_save_command,
    handle_lifepath_start_command,
    handle_lifepath_summary_command,
)
from spacemarches.services.lifepath_service import (
    apply_step15_gear_packs,
    compute_final_sheet,
    finalize_and_export_session,
    perform_step_roll,
    reallocate_step15_overflow,
    resolve_pending_choice,
    skip_optional_step,
    start_lifepath_session,
    use_flex_reroll,
)

User = get_user_model()


def _mock_interaction(discord_user_id: str, display_name: str = "LifepathPlayer"):
    interaction = MagicMock()
    interaction.id = 990011
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = discord_user_id
    interaction.user.display_name = display_name
    interaction.user.mention = f"<@{discord_user_id}>"
    interaction.channel = MagicMock()
    interaction.channel.id = 888777
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    return interaction


class LifepathDatabaseAndSeedTests(TestCase):
    def test_seed_dry_run_and_idempotency_and_custom_preservation(self):
        dry_out = StringIO()
        call_command("seed_lifepath_data", "--dry-run", stdout=dry_out)
        self.assertIn("[dry-run] Lifepath seed:", dry_out.getvalue())
        self.assertEqual(LifepathTable.objects.count(), 0)

        call_command("seed_lifepath_data", stdout=StringIO())
        t_count = LifepathTable.objects.count()
        e_count = LifepathEntry.objects.count()
        self.assertGreaterEqual(t_count, 70)
        self.assertGreaterEqual(e_count, 1500)

        # Customize an entry as Storyteller and verify re-seed preserves it
        entry = LifepathEntry.objects.get(table__slug="native-tongue", title="English")
        entry.title = "Spacemarches Cant"
        entry.is_custom = True
        entry.save()

        call_command("seed_lifepath_data", stdout=StringIO())
        self.assertEqual(LifepathTable.objects.count(), t_count)
        entry.refresh_from_db()
        self.assertEqual(entry.title, "Spacemarches Cant")

        # --overwrite-custom restores seeded value
        call_command("seed_lifepath_data", "--overwrite-custom", stdout=StringIO())
        entry.refresh_from_db()
        self.assertEqual(entry.title, "English")
        self.assertFalse(entry.is_custom)


class LifepathEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_lifepath_data", stdout=StringIO())

    def setUp(self):
        self.user = User.objects.create_user(username="lp-tester")

    def test_full_path_debt_flex_reroll_and_export(self):
        session = start_lifepath_session(
            character_name="Kestrel Nine",
            user=self.user,
            hardcore_flex=False,
        )
        self.assertEqual(session.current_step, 2)
        self.assertEqual(session.state["flex_total"], 1)
        self.assertEqual(session.state["flex_rerolls_remaining"], 1)

        # Step 2: Choose Factotum -> Step 3
        res2 = perform_step_roll(session, chosen_entry_code="apt-4-0-factotum")
        self.assertEqual(res2["entry_title"], "Factotum")
        self.assertEqual(session.current_step, 3)

        # Use Flex reroll on Step 2 right after choosing/rolling -> reverts Factotum and re-rolls Step 2
        reroll_res = use_flex_reroll(session, seed=42)
        self.assertIn("entry_title", reroll_res)
        self.assertEqual(session.state["flex_rerolls_remaining"], 0)
        self.assertEqual(session.state["flex_total"], 1)  # non-hardcore preserves final Flex
        self.assertEqual(session.current_step, 3)

        # Second Flex reroll fails because 0 rerolls left
        with self.assertRaises(ValueError):
            use_flex_reroll(session, seed=7)

        # Step 3: Native Tongue -> choose English
        perform_step_roll(session, chosen_entry_code="lang-15-english")
        self.assertIn("English", session.state["languages"])
        self.assertEqual(session.current_step, 4)

        # Step 4A: Background Path -> Colonist -> Step 4B Orbital
        perform_step_roll(session, chosen_entry_code="bg-colonist")
        self.assertEqual(session.state["active_table_slug"], "background-colonist")
        perform_step_roll(session, chosen_entry_code="4.1-orbital", seed=5)
        self.assertEqual(session.current_step, 5)
        self.assertTrue(session.state["morph"]["name"])

        # Step 5: Youth Event
        perform_step_roll(session, seed=11)
        while session.state["pending_choices"]:
            resolve_pending_choice(session, auto_roll=True, seed=11)
        while session.state["pending_sub_rolls"]:
            perform_step_roll(session, seed=11)
            while session.state["pending_choices"]:
                resolve_pending_choice(session, auto_roll=True, seed=11)
        self.assertGreaterEqual(session.current_step, 6)

        # Step 6..12 advance with deterministic seed
        while session.current_step < 13:
            perform_step_roll(session, seed=19)
            while session.state["pending_choices"]:
                resolve_pending_choice(session, auto_roll=True, seed=19)
            while session.state["pending_sub_rolls"]:
                perform_step_roll(session, seed=19)
                while session.state["pending_choices"]:
                    resolve_pending_choice(session, auto_roll=True, seed=19)

        self.assertEqual(session.current_step, 13)
        perform_step_roll(session, table_slug="firewall-event", seed=23)
        while session.state["pending_choices"]:
            resolve_pending_choice(session, auto_roll=True, seed=23)
        while session.state["pending_sub_rolls"]:
            perform_step_roll(session, seed=23)
            while session.state["pending_choices"]:
                resolve_pending_choice(session, auto_roll=True, seed=23)

        self.assertEqual(session.current_step, 14)
        skip_optional_step(session, reason="No optional story event")
        self.assertEqual(session.current_step, 15)

        sheet = apply_step15_gear_packs(
            session,
            campaign_pack_title="Firewall Agent / Criminal",
            profession_pack_title="Hacker",
            selected_motivations=session.state["motivations_pool"][:3],
        )
        self.assertEqual(sheet["gear_pack_campaign"], "Firewall Agent / Criminal")
        self.assertEqual(sheet["gear_pack_profession"], "Hacker")
        self.assertIn("Fray", sheet["active_skills"])
        self.assertIn("Perceive", sheet["active_skills"])

        session, gen_char = finalize_and_export_session(
            session,
            user=self.user,
            character_name="Kestrel Nine Final",
            create_dossier=True,
        )
        self.assertEqual(session.status, LifepathSession.STATUS_COMPLETED)
        self.assertIsNotNone(gen_char)
        self.assertEqual(gen_char.source_system, GeneratedCharacter.SOURCE_LIFE_PATH)
        self.assertIsNotNone(gen_char.dossier)
        self.assertEqual(gen_char.character_name, "Kestrel Nine Final")

    def test_infolife_and_lost_age_skips_and_uplift_cap(self):
        # Infolife skips Step 7
        s_info = start_lifepath_session(character_name="AGI-1")
        perform_step_roll(s_info, chosen_entry_code="apt-5-0-inquirer")
        perform_step_roll(s_info, chosen_entry_code="lang-15-english")
        perform_step_roll(s_info, chosen_entry_code="bg-infolife")
        perform_step_roll(s_info, chosen_entry_code="4.6-machine-agi", seed=3)
        # Complete Youth event (pick non-skipping seed)
        s_info.current_step = 6
        s_info.state["active_table_slug"] = "age"
        s_info.save()
        perform_step_roll(s_info, seed=1)
        self.assertIn("Infolife 20s", s_info.state["age_label"])
        self.assertEqual(s_info.current_step, 8)

        # Lost skips Steps 7 and 8
        s_lost = start_lifepath_session(character_name="Lost-9")
        perform_step_roll(s_lost, chosen_entry_code="apt-5-0-inquirer")
        perform_step_roll(s_lost, chosen_entry_code="lang-15-english")
        perform_step_roll(s_lost, chosen_entry_code="bg-lost")
        perform_step_roll(s_lost, chosen_entry_code="4.8-long-past-normal", seed=3)
        while s_lost.state["pending_choices"]:
            resolve_pending_choice(s_lost, auto_roll=True, seed=3)
        s_lost.current_step = 6
        s_lost.state["active_table_slug"] = "age"
        s_lost.save()
        perform_step_roll(s_lost, seed=2)
        self.assertIn("9 chronological", s_lost.state["age_label"])
        self.assertEqual(s_lost.current_step, 9)

        # Uplift age capped at <= 50
        s_uplift = start_lifepath_session(character_name="Neo-Bonobo")
        perform_step_roll(s_uplift, chosen_entry_code="apt-1-0-actioneer")
        perform_step_roll(s_uplift, chosen_entry_code="lang-15-english")
        perform_step_roll(s_uplift, chosen_entry_code="bg-uplift")
        perform_step_roll(s_uplift, chosen_entry_code="4.10-escapee", seed=4)
        s_uplift.current_step = 6
        s_uplift.state["active_table_slug"] = "age"
        s_uplift.save()
        perform_step_roll(s_uplift, seed=99)
        self.assertLessEqual(int(s_uplift.state["age_years"]), 50)

    def test_hardcore_flex_and_80_cap_reallocation(self):
        s = start_lifepath_session(character_name="Hardcore", hardcore_flex=True)
        perform_step_roll(s, chosen_entry_code="apt-4-0-factotum")
        use_flex_reroll(s, seed=1)
        self.assertEqual(s.state["flex_total"], 0)
        self.assertEqual(s.state["flex_rerolls_remaining"], 0)

        # Force >80 skill overflow and reallocate
        s.state["skills"]["Guns"] = 75  # +15 REF = 90 (10 over 80)
        s.save()
        sheet = compute_final_sheet(s.state)
        self.assertEqual(sheet["active_skills"]["Guns"]["total"], 80)
        self.assertEqual(sheet["skill_overflows"][0]["excess"], 10)
        updated = reallocate_step15_overflow(s, source_name="Guns", target_name="Melee")
        self.assertEqual(updated["skill_overflows"], [])
        self.assertEqual(updated["active_skills"]["Guns"]["total"], 80)
        self.assertEqual(updated["active_skills"]["Melee"]["raw"], 10)


class LifepathDiscordBotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_lifepath_data", stdout=StringIO())

    def setUp(self):
        self.user = User.objects.create_user(username="discord-lp-user")
        DiscordLink.objects.create(user=self.user, discord_user_id="444555666")

    def test_build_bot_registers_lifepath_group(self):
        client = build_bot()
        cmd_names = {cmd.name for cmd in client.tree.get_commands()}
        self.assertIn("lifepath", cmd_names)
        lp_group = next(cmd for cmd in client.tree.get_commands() if cmd.name == "lifepath")
        sub_names = {sub.name for sub in lp_group.commands}
        self.assertEqual(sub_names, {"start", "resume", "roll", "choose", "reroll", "summary", "save"})

    def test_discord_lifepath_start_roll_reroll_component_and_save(self):
        inter1 = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_start_command)(inter1, character_name="Vesper Echo")
        kwargs = inter1.response.send_message.call_args.kwargs
        self.assertIn("EP2e Life Path: Vesper Echo", kwargs["embed"].title)
        view = kwargs["view"]
        self.assertIsInstance(view, LifepathHubView)

        session = LifepathSession.objects.get(discord_user_id="444555666")
        self.assertEqual(session.current_step, 2)

        # Roll Step 2 via /lifepath roll
        inter2 = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_roll_command)(inter2)
        session.refresh_from_db()
        self.assertEqual(session.current_step, 3)

        # Spend Flex via /lifepath reroll
        inter3 = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_reroll_command)(inter3)
        session.refresh_from_db()
        self.assertEqual(session.state["flex_rerolls_remaining"], 0)
        self.assertIn("Spent 1 Ego Flex", inter3.response.send_message.call_args.kwargs["content"])

        # Choose Native Tongue via /lifepath choose
        inter4 = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_choose_command)(inter4, option="English")
        session.refresh_from_db()
        self.assertIn("English", session.state["languages"])
        self.assertEqual(session.current_step, 4)

        # Test persistent sm:lp:roll component routing (stateless fallback after restart)
        inter5 = _mock_interaction("444555666")
        handled = async_to_sync(handle_persistent_component_interaction)(
            inter5,
            custom_id=f"sm:lp:roll:{session.pk}:background-path:444555666",
            data={},
        )
        self.assertTrue(handled)
        inter5.response.edit_message.assert_awaited_once()

        # Non-owner blocked from interacting
        stranger = _mock_interaction("999999999", display_name="Intruder")
        async_to_sync(handle_lifepath_component_interaction)(
            stranger,
            custom_id=f"sm:lp:roll:{session.pk}:background-path:444555666",
            data={},
        )
        self.assertTrue(stranger.response.send_message.call_args.kwargs.get("ephemeral"))

        # Resume, Summary & Save
        inter_resume = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_resume_command)(inter_resume)
        inter_resume.response.send_message.assert_awaited_once()

        inter_sum = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_summary_command)(inter_sum)
        self.assertIsInstance(inter_sum.response.send_message.call_args.kwargs["file"], discord.File)

        inter_save = _mock_interaction("444555666")
        async_to_sync(handle_lifepath_save_command)(inter_save, character_name="Vesper Final", create_dossier=True)
        session.refresh_from_db()
        self.assertEqual(session.status, LifepathSession.STATUS_COMPLETED)
        self.assertIsNotNone(session.generated_character)
        self.assertEqual(session.generated_character.source_system, GeneratedCharacter.SOURCE_LIFE_PATH)
        self.assertTrue(CharacterDossier.objects.filter(character_name="Vesper Final", user=self.user).exists())
