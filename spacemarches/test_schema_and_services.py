from django.contrib.auth import get_user_model
from django.test import TestCase

from spacemarches.models import AgentSaveSlot, CharacterDossier, DiscordLink
from spacemarches.questionnaire import (
    get_all_questions,
    get_attribution_notice,
    get_children,
    get_core_questions,
    get_question,
)
from spacemarches.services.dossier_service import (
    complete_discord_link,
    export_dossier_markdown,
    generate_discord_link_code,
    save_dossier_answer,
)
from spacemarches.services.game_sync_service import load_agent_save, sync_agent_save

User = get_user_model()


class QuestionnaireSchemaTests(TestCase):
    def test_schema_has_unique_ids_all_tiers_and_attribution(self):
        all_qs = get_all_questions(include_sensitive=True)
        ids = [q["id"] for q in all_qs]
        self.assertEqual(len(ids), len(set(ids)))

        tiers = {q["tier"] for q in all_qs}
        self.assertEqual(tiers, {"core", "deep", "sensitive_appendix"})

        # Verify every core question 1..16
        core_ids = {q["id"] for q in get_core_questions()}
        self.assertEqual(core_ids, {str(i) for i in range(1, 17)})

        # Verify expected sub-question trees
        expected_ids = set()
        expected_ids.update(f"6.1{ch}" for ch in "abcdefghijk")
        expected_ids.update(f"6.2{ch}" for ch in "abcdefghijklmno")
        expected_ids.update(f"11{ch}" for ch in "abcdefghijklmnopqrstuvwx")
        expected_ids.update(f"12{ch}" for ch in "ABCD")
        expected_ids.update(f"13{ch}" for ch in "abcde")
        expected_ids.update(f"13d{i}" for i in range(1, 7))
        expected_ids.update(f"14{ch}" for ch in "abcdefgh")
        expected_ids.update(f"15{ch}" for ch in "abcdef")
        expected_ids.update(f"16{ch}" for ch in "abc")
        self.assertTrue(expected_ids.issubset(set(ids)))

        # Sensitive appendix filtering
        non_sensitive_ids = {q["id"] for q in get_all_questions(include_sensitive=False)}
        for sid in (f"13d{i}" for i in range(1, 7)):
            self.assertNotIn(sid, non_sensitive_ids)
        self.assertEqual(len(get_children("13d", include_sensitive=True)), 6)
        self.assertEqual(len(get_children("13d", include_sensitive=False)), 0)

        # Attribution notice
        notice = get_attribution_notice()
        self.assertIn("ShadowDragon8685", notice)
        self.assertIn("GearheadLydia", notice)
        self.assertIn("CC BY-NC-SA 3.0", notice)


class DossierAndSyncServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="agent-kestrel")
        self.other_user = User.objects.create_user(username="agent-rook")
        self.dossier = CharacterDossier.objects.create(
            user=self.user,
            character_name="Vesper Nine",
            slug="vesper-nine",
        )

    def test_save_dossier_answer_preserves_revisions_and_privacy(self):
        with self.assertRaises(ValueError):
            save_dossier_answer(self.dossier, "999z", "Invalid prompt")

        stats1 = save_dossier_answer(
            self.dossier,
            question_id="15a",
            answer_text="Tracking the missing shuttle from Locus.",
            session_tag="Session 0",
            source="web",
            is_gm_only=True,
        )
        self.assertEqual(stats1["revision_count"], 0)
        self.assertTrue(stats1["is_gm_only"])
        self.assertIn("15a", self.dossier.private_keys)

        stats2 = save_dossier_answer(
            self.dossier,
            question_id="15a",
            answer_text="Shuttle logs point to an exsurgent beacon on Titan.",
            session_tag="Post-Session 1",
            source="discord",
            is_gm_only=None,  # keep existing GM flag
        )
        self.assertEqual(stats2["revision_count"], 1)
        self.assertTrue(stats2["is_gm_only"])
        entry = self.dossier.responses["15a"]
        self.assertEqual(entry["source"], "discord")
        self.assertEqual(entry["session_tag"], "Post-Session 1")
        self.assertEqual(entry["revisions"][0]["answer"], "Tracking the missing shuttle from Locus.")
        self.assertEqual(entry["revisions"][0]["session_tag"], "Session 0")

        # Export respects include_private flag and attribution
        save_dossier_answer(self.dossier, "1", "Vesper Nine", session_tag="Session 0", source="web")
        public_md = export_dossier_markdown(self.dossier, include_private=False)
        self.assertIn("Vesper Nine", public_md)
        self.assertNotIn("exsurgent beacon on Titan", public_md)
        self.assertIn("CC BY-NC-SA 3.0", public_md)

        full_md = export_dossier_markdown(self.dossier, include_private=True)
        self.assertIn("exsurgent beacon on Titan", full_md)
        self.assertIn("[GM EYES ONLY]", full_md)

    def test_sensitive_appendix_gating_on_export(self):
        save_dossier_answer(self.dossier, "13d1", "Lost beta fork during farcast.", source="web")
        hidden_md = export_dossier_markdown(self.dossier, include_private=True)
        self.assertNotIn("Lost beta fork during farcast.", hidden_md)

        self.dossier.show_sensitive_appendix = True
        self.dossier.save(update_fields=["show_sensitive_appendix"])
        revealed_md = export_dossier_markdown(self.dossier, include_private=True)
        self.assertIn("Lost beta fork during farcast.", revealed_md)

    def test_discord_link_code_lifecycle(self):
        code = generate_discord_link_code(self.user)
        self.assertEqual(len(code), 8)

        link = complete_discord_link(code.lower(), "9876543210")
        self.assertEqual(link.user, self.user)
        self.assertEqual(link.discord_user_id, "9876543210")
        self.assertIsNone(link.link_code)
        self.assertIsNotNone(link.linked_at)

        # Consumed code cannot be reused
        with self.assertRaises(ValueError):
            complete_discord_link(code, "111222333")

        # Different user cannot claim same discord_user_id
        other_code = generate_discord_link_code(self.other_user)
        with self.assertRaises(ValueError):
            complete_discord_link(other_code, "9876543210")

    def test_agent_save_slot_roundtrip(self):
        empty = load_agent_save(self.user, "auto")
        self.assertFalse(empty["exists"])
        self.assertEqual(empty["raw_state"], {})

        slot, created = sync_agent_save(
            self.user,
            slot_name="auto",
            raw_state={"spacemarches:node": "sector-7", "inventory": ["stack-key"]},
            clearance_summary={"level": "CL-3", "unlocked_logs": ["LOG-042"]},
        )
        self.assertTrue(created)
        self.assertEqual(AgentSaveSlot.objects.filter(user=self.user).count(), 1)

        loaded = load_agent_save(self.user, "auto")
        self.assertTrue(loaded["exists"])
        self.assertEqual(loaded["raw_state"]["spacemarches:node"], "sector-7")
        self.assertEqual(loaded["clearance_summary"]["level"], "CL-3")
