import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from spacemarches.models import ArchiveEntry, CharacterDossier, ForumPost, ForumThread
from spacemarches.selectors import get_user_spacemarches_summary
from spacemarches.services.dossier_service import (
    complete_discord_link,
    create_character_dossier_for_discord,
    generate_discord_link_code,
    register_discord_intake_invite,
    save_dossier_answer,
)
from spacemarches.services.game_sync_service import sync_agent_save

User = get_user_model()


class SpacemarchesViewsAndSelectorsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="player1")
        self.other = User.objects.create_user(username="player2")
        self.admin = User.objects.create_user(username="st-admin", is_staff=True)
        self.public_archive = ArchiveEntry.objects.create(
            slug="incident-zero",
            title="Incident Zero",
            classification_level="DECLASSIFIED",
            body="**Cleared briefing** for public review.",
            is_public=True,
            author=self.user,
        )
        self.secret_archive = ArchiveEntry.objects.create(
            slug="black-vault",
            title="Black Vault",
            classification_level="OMEGA-REDACTED",
            body="CLASSIFIED-SECRET-PAYLOAD",
            is_public=False,
            author=self.user,
        )
        self.thread = ForumThread.objects.create(
            title="Field Notes on Incident Zero",
            slug="field-notes-incident-zero",
            author=self.user,
            related_archive=self.public_archive,
            is_public=True,
            body="Initial discussion.",
        )
        self.dossier = CharacterDossier.objects.create(
            user=self.user,
            character_name="Cassian Mire",
            slug="cassian-mire",
        )

    def test_public_routes_accessible_and_hidden_archives_blocked(self):
        for name, kwargs in [
            ("spacemarches:portal", {}),
            ("spacemarches:archive_list", {}),
            ("spacemarches:archive_detail", {"slug": self.public_archive.slug}),
            ("spacemarches:forum_list", {}),
            ("spacemarches:forum_detail", {"slug": self.thread.slug}),
        ]:
            resp = self.client.get(reverse(name, kwargs=kwargs))
            self.assertEqual(resp.status_code, 200)

        archive_list = self.client.get(reverse("spacemarches:archive_list"))
        self.assertContains(archive_list, "Incident Zero")
        self.assertNotContains(archive_list, "Black Vault")

        secret_detail = self.client.get(
            reverse("spacemarches:archive_detail", kwargs={"slug": self.secret_archive.slug})
        )
        self.assertEqual(secret_detail.status_code, 404)

    def test_authenticated_routes_redirect_anonymous_users(self):
        protected = [
            ("GET", reverse("spacemarches:terminal")),
            ("GET", reverse("spacemarches:api_sync")),
            ("POST", reverse("spacemarches:api_sync")),
            ("GET", reverse("spacemarches:dossier_list")),
            ("GET", reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})),
            ("POST", reverse("spacemarches:dossier_answer", kwargs={"slug": self.dossier.slug})),
            ("GET", reverse("spacemarches:dossier_export", kwargs={"slug": self.dossier.slug})),
            ("POST", reverse("spacemarches:forum_new")),
            ("POST", reverse("spacemarches:forum_reply", kwargs={"slug": self.thread.slug})),
        ]
        for method, url in protected:
            with self.subTest(method=method, url=url):
                resp = self.client.get(url) if method == "GET" else self.client.post(url, {})
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/accounts/login/", resp["Location"])

    def test_terminal_and_api_sync_roundtrip(self):
        self.client.force_login(self.user)
        term_resp = self.client.get(reverse("spacemarches:terminal"))
        self.assertEqual(term_resp.status_code, 200)
        self.assertContains(term_resp, "SpacemarchesBridge")

        post_resp = self.client.post(
            reverse("spacemarches:api_sync"),
            data=json.dumps(
                {
                    "slot_name": "campaign-1",
                    "raw_state": {"node": "airlock-3"},
                    "clearance_summary": {"level": "LEVEL-2", "unlocked_logs": ["LOG-12"]},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json()["status"], "ok")

        get_resp = self.client.get(reverse("spacemarches:api_sync") + "?slot=campaign-1")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["raw_state"]["node"], "airlock-3")

    def test_dossier_ajax_answer_privacy_and_export(self):
        self.client.force_login(self.user)
        detail_resp = self.client.get(
            reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})
        )
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "Dive Deeper")
        self.assertContains(detail_resp, 'class="btn filter-pill active-pill" data-filter="core"')
        self.assertContains(detail_resp, "Auto by Prompt")
        self.assertContains(detail_resp, "Origin &middot; Pre-Fall Default")
        self.assertContains(detail_resp, "Now &middot; 10 AF+")
        self.assertContains(detail_resp, "Post-Fall Sol-Date")
        self.assertContains(detail_resp, "Preview GM Redaction")
        self.assertNotContains(detail_resp, "Active Session Tag")
        self.assertNotContains(detail_resp, 'data-question-id="13d1"')

        # Sensitive appendix rejected until opted in
        blocked_resp = self.client.post(
            reverse("spacemarches:dossier_answer", kwargs={"slug": self.dossier.slug}),
            data=json.dumps({"question_id": "13d1", "answer_text": "Redacted"}),
            content_type="application/json",
        )
        self.assertEqual(blocked_resp.status_code, 400)

        # Opt in and verify card is now revealed
        self.client.post(
            reverse("spacemarches:dossier_toggle_sensitive", kwargs={"slug": self.dossier.slug})
        )
        self.dossier.refresh_from_db()
        self.assertTrue(self.dossier.show_sensitive_appendix)
        revealed_resp = self.client.get(
            reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})
        )
        self.assertContains(revealed_resp, 'data-question-id="13d1"')

        # Save Character Creation at Pre-Fall, then Post-Action Report at Post-Fall Sol 2.500
        ans_resp = self.client.post(
            reverse("spacemarches:dossier_answer", kwargs={"slug": self.dossier.slug}),
            data=json.dumps(
                {
                    "question_id": "1",
                    "answer_text": "Cassian Mire / Agent Glass",
                    "entry_kind": "character_creation",
                    "stardate_era": "pre_fall",
                    "is_gm_only": False,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(ans_resp.status_code, 200)
        self.assertEqual(ans_resp.json()["core_answered"], 1)
        self.assertEqual(ans_resp.json()["version_label"], "Pre-Fall_v1")

        # Clarify Pre-Fall -> Pre-Fall_v2
        clarify_resp = self.client.post(
            reverse("spacemarches:dossier_answer", kwargs={"slug": self.dossier.slug}),
            data=json.dumps(
                {
                    "question_id": "1",
                    "answer_text": "Cassian Mire (Backup Fork: Glass)",
                    "entry_kind": "post_action_report",
                    "stardate_era": "post_fall",
                    "sol_date": "2.500",
                    "is_gm_only": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(clarify_resp.status_code, 200)
        self.assertEqual(clarify_resp.json()["version_label"], "Sol 2.500_v1")
        self.assertEqual(clarify_resp.json()["revision_count"], 1)
        self.assertTrue(clarify_resp.json()["is_gm_only"])

        # Blank overwrite is blocked (400)
        blank_resp = self.client.post(
            reverse("spacemarches:dossier_answer", kwargs={"slug": self.dossier.slug}),
            data=json.dumps(
                {
                    "question_id": "1",
                    "answer_text": "",
                    "entry_kind": "post_action_report",
                    "stardate_era": "post_fall",
                    "sol_date": "3.000",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(blank_resp.status_code, 400)

        # privacy_only toggle sets GM-only False without disturbing answer/revisions
        priv_resp = self.client.post(
            reverse("spacemarches:dossier_answer", kwargs={"slug": self.dossier.slug}),
            data=json.dumps({"question_id": "1", "privacy_only": True, "is_gm_only": False}),
            content_type="application/json",
        )
        self.assertEqual(priv_resp.status_code, 200)
        self.assertFalse(priv_resp.json()["is_gm_only"])
        self.assertEqual(priv_resp.json()["revision_count"], 1)

        export_resp = self.client.get(
            reverse("spacemarches:dossier_export", kwargs={"slug": self.dossier.slug})
        )
        self.assertEqual(export_resp.status_code, 200)
        self.assertContains(export_resp, "Cassian Mire (Backup Fork: Glass)")
        self.assertContains(export_resp, "Sol 2.500_v1")
        self.assertContains(export_resp, "Pre-Fall_v1")

        # Another user cannot view or edit this dossier
        self.client.force_login(self.other)
        other_resp = self.client.get(
            reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})
        )
        self.assertEqual(other_resp.status_code, 404)

    def test_authenticated_forum_posting_and_selector_summary(self):
        self.client.force_login(self.user)
        reply_resp = self.client.post(
            reverse("spacemarches:forum_reply", kwargs={"slug": self.thread.slug}),
            {"body": "Confirmed sensor anomalies."},
        )
        self.assertEqual(reply_resp.status_code, 302)
        self.assertTrue(ForumPost.objects.filter(thread=self.thread, author=self.user).exists())

        save_dossier_answer(self.dossier, "1", "Cassian", source="web")
        sync_agent_save(
            self.user,
            slot_name="auto",
            raw_state={"step": 2},
            clearance_summary={"level": "CL-2", "unlocked_logs": ["LOG-009"]},
        )
        summary = get_user_spacemarches_summary(self.user)
        self.assertTrue(summary["authenticated"])
        self.assertEqual(summary["dossier_count"], 1)
        self.assertEqual(summary["unlocked_logs"], ["LOG-009"])
        self.assertEqual(summary["active_dossiers"][0]["character_name"], "Cassian Mire")

        home_resp = self.client.get(reverse("home"))
        self.assertEqual(home_resp.status_code, 200)
        self.assertNotContains(home_resp, "/spacemarches/")

        status_resp = self.client.get(reverse("participant_status"))
        self.assertEqual(status_resp.status_code, 200)
        self.assertNotContains(status_resp, "/spacemarches/")

        portal_resp = self.client.get(reverse("spacemarches:portal"))
        self.assertEqual(portal_resp.status_code, 200)
        self.assertNotContains(portal_resp, "/write/request/")

    def test_admin_roster_unclaimed_and_player_control_override(self):
        register_discord_intake_invite("444555666", invited_by_user=self.admin)
        unclaimed = create_character_dossier_for_discord(
            "444555666",
            "Ghost Signal",
            invited_by_user=self.admin,
        )
        save_dossier_answer(unclaimed, "1", "Ghost Signal", source="discord")

        # Non-staff user cannot access unclaimed or another player's dossiers and sees no GM Roster
        self.client.force_login(self.other)
        list_other = self.client.get(reverse("spacemarches:dossier_list"))
        self.assertEqual(list_other.status_code, 200)
        self.assertNotContains(list_other, "GM / Admin Roster")
        self.assertEqual(
            self.client.get(
                reverse("spacemarches:dossier_detail_by_id", kwargs={"pk": unclaimed.pk})
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("spacemarches:dossier_detail_by_id", kwargs={"pk": self.dossier.pk})
            ).status_code,
            404,
        )

        # Staff admin sees unclaimed onboarding dossiers and player dossiers in GM / Admin Roster
        self.client.force_login(self.admin)
        list_admin = self.client.get(reverse("spacemarches:dossier_list"))
        self.assertEqual(list_admin.status_code, 200)
        self.assertContains(list_admin, "GM / Admin Roster")
        self.assertContains(list_admin, "Ghost Signal")
        self.assertContains(list_admin, "Unclaimed (Discord:444555666)")
        self.assertContains(list_admin, "Cassian Mire")

        # Admin can inspect, edit, and export unclaimed dossier by ID
        admin_detail = self.client.get(
            reverse("spacemarches:dossier_detail_by_id", kwargs={"pk": unclaimed.pk})
        )
        self.assertEqual(admin_detail.status_code, 200)
        self.assertContains(admin_detail, "Admin View")
        self.assertContains(admin_detail, "awaiting /link")

        admin_save = self.client.post(
            reverse("spacemarches:dossier_answer_by_id", kwargs={"pk": unclaimed.pk}),
            data=json.dumps(
                {
                    "question_id": "2",
                    "answer_text": "Firewall sleeper agent",
                    "entry_kind": "character_creation",
                    "stardate_era": "auto",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(admin_save.status_code, 200)
        self.assertEqual(admin_save.json()["core_answered"], 2)

        admin_export = self.client.get(
            reverse("spacemarches:dossier_export_by_id", kwargs={"pk": unclaimed.pk}) + "?include_private=1"
        )
        self.assertEqual(admin_export.status_code, 200)
        self.assertContains(admin_export, "Firewall sleeper agent")

        # Player links their Discord and takes control on website
        code = generate_discord_link_code(self.other)
        complete_discord_link(code, "444555666")
        unclaimed.refresh_from_db()
        self.assertEqual(unclaimed.user, self.other)

        self.client.force_login(self.other)
        claimed_list = self.client.get(reverse("spacemarches:dossier_list"))
        self.assertContains(claimed_list, "Ghost Signal")

        # Admin STILL retains edit access even after the player claims control
        self.client.force_login(self.admin)
        post_claim_admin_save = self.client.post(
            reverse("spacemarches:dossier_answer_by_id", kwargs={"pk": unclaimed.pk}),
            data=json.dumps(
                {
                    "question_id": "3",
                    "answer_text": "Morph logged by ST",
                    "entry_kind": "post_action_report",
                    "stardate_era": "post_fall",
                    "sol_date": "10.100",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(post_claim_admin_save.status_code, 200)
        self.assertEqual(post_claim_admin_save.json()["core_answered"], 3)

