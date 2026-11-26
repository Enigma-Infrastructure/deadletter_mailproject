import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from spacemarches.models import (
    CharacterDossier,
    GeneratedCharacter,
    ProtectionAccessLog,
)
from spacemarches.services.protection_service import (
    clear_secret,
    is_unlocked,
    protection_state,
    set_secret,
    verify_secret,
)

User = get_user_model()


class ProtectionServiceTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="alice", password="pw12345!")
        self.user = user
        self.dossier = CharacterDossier.objects.create(
            user=user, character_name="Test Dossier", slug="test-dossier",
        )
        self.sheet = GeneratedCharacter.objects.create(
            user=user,
            dossier=self.dossier,
            character_name="Test Sheet",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data={},
            summary={},
            status=GeneratedCharacter.STATUS_COMPLETED,
        )

    def test_set_and_verify_secret(self):
        set_secret(self.sheet, "What does the muse recall?", "Kx9-Muse")
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.secret_puzzle_prompt, "What does the muse recall?")
        self.assertTrue(self.sheet.secret_answer_hash)
        self.assertNotIn("Kx9-Muse", self.sheet.secret_answer_hash)
        self.assertTrue(verify_secret(self.sheet, "Kx9-Muse"))
        self.assertFalse(verify_secret(self.sheet, "wrong"))

    def test_clear_secret(self):
        set_secret(self.sheet, "prompt", "answer")
        clear_secret(self.sheet)
        self.assertFalse(self.sheet.secret_answer_hash)
        self.assertFalse(self.sheet.secret_puzzle_prompt)

    def test_protection_state_none(self):
        state = protection_state(self.sheet, None, viewer=self.user)
        self.assertEqual(state["protection"], "none")
        self.assertFalse(state["locked"])

    def test_protection_state_secret_locked_for_owner(self):
        set_secret(self.sheet, "What does the muse recall?", "Kx9")
        self.sheet.protection = GeneratedCharacter.PROTECTION_SECRET
        self.sheet.save()
        # owner is still locked by the secret
        state = protection_state(self.sheet, None, viewer=self.user)
        self.assertEqual(state["protection"], "secret")
        self.assertTrue(state["locked"])
        self.assertFalse(state["unlocked"])

    def test_protection_state_st_only(self):
        self.sheet.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.sheet.save()
        state_regular = protection_state(self.sheet, None, viewer=self.user)
        self.assertTrue(state_regular["locked"])
        self.assertEqual(state_regular["protection"], "st_only")

        st_user = User.objects.create_user(username="st", password="pw12345!", is_st=True)
        state_st = protection_state(self.sheet, None, viewer=st_user)
        self.assertFalse(state_st["locked"])

    def test_is_st_admin_split(self):
        """Storyteller marking is distinct from admin marking."""
        admin = User.objects.create_user(username="admin", password="pw12345!", is_staff=True)
        self.assertFalse(admin.is_st)
        self.assertTrue(admin.is_staff)
        st_only = User.objects.create_user(username="st", password="pw12345!", is_st=True)
        self.assertTrue(st_only.is_st)
        self.assertFalse(st_only.is_staff)


class ReviewSurfaceTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="owner", password="pw12345!")
        self.owner = user
        self.dossier = CharacterDossier.objects.create(
            user=user, character_name="Public Dossier", slug="public-dossier",
        )
        self.sheet = GeneratedCharacter.objects.create(
            user=user,
            dossier=self.dossier,
            character_name="Public Sheet",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data={},
            summary={},
            status=GeneratedCharacter.STATUS_COMPLETED,
            public_view=True,
        )
        self.review_url = reverse("spacemarches:dossier_review", kwargs={"slug": self.dossier.slug})

    def test_review_surface_renders_public_sheet(self):
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Public Sheet")

    def test_review_surface_locked_for_draft_sheet(self):
        self.sheet.status = GeneratedCharacter.STATUS_DRAFT
        self.sheet.save()
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Public Sheet")

    def test_review_surface_locked_for_non_public_sheet(self):
        self.sheet.public_view = False
        self.sheet.save()
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Public Sheet")

    def test_secret_sheet_locked_then_unlocked_with_cipher(self):
        set_secret(self.sheet, "What does the muse recall?", "Kx9-Muse")
        self.sheet.protection = GeneratedCharacter.PROTECTION_SECRET
        self.sheet.save()

        # locked initially
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "What does the muse recall?")
        self.assertNotContains(resp, "Public Sheet")

        # wrong answer keeps the lock
        resp = self.client.post(
            self.review_url,
            {"action": "unlock_sheet", "sheet_pk": self.sheet.pk, "answer": "wrong"},
        )
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(self.review_url)
        self.assertNotContains(resp, "Public Sheet")

        # right answer unlocks
        resp = self.client.post(
            self.review_url,
            {"action": "unlock_sheet", "sheet_pk": self.sheet.pk, "answer": "Kx9-Muse"},
        )
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(self.review_url)
        self.assertContains(resp, "Public Sheet")

    def test_st_only_sheet_locked_for_regular_user(self):
        self.sheet.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.sheet.save()
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Public Sheet")

    def test_st_only_sheet_viewable_by_st_and_logged(self):
        st_user = User.objects.create_user(username="st", password="pw12345!", is_st=True)
        self.sheet.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.sheet.save()
        self.client.login(username="st", password="pw12345!")
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Public Sheet")

        log_entry = ProtectionAccessLog.objects.filter(
            target_kind="character", target_pk=self.sheet.pk, viewer__username="st",
        ).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.protection_type, GeneratedCharacter.PROTECTION_ST_ONLY)

    def test_secret_dossier_locked_then_unlocked(self):
        set_secret(self.dossier, "What does the muse recall?", "Kx9-Dossier")
        self.dossier.protection = GeneratedCharacter.PROTECTION_SECRET
        self.dossier.save()
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Sheets in this review")

        resp = self.client.post(
            self.review_url,
            {"action": "unlock_dossier", "answer": "Kx9-Dossier"},
        )
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(self.review_url)
        self.assertContains(resp, "Sheets in this review")

    def test_anon_banner_server_rendered_for_anonymous_users(self):
        resp = self.client.get(reverse("spacemarches:meshnet"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "These characters are not saved")

    def test_anon_banner_absent_for_authenticated_users(self):
        self.client.login(username="owner", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:meshnet"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "These characters are not saved")


class SheetLifecycleTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="owner", password="pw12345!")
        self.user = user
        self.sheet = GeneratedCharacter.objects.create(
            user=user,
            character_name="Lifecycle Sheet",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data={},
            summary={},
            status=GeneratedCharacter.STATUS_DRAFT,
        )
        self.client.login(username="owner", password="pw12345!")

    def test_mark_completed_sets_timestamp(self):
        resp = self.client.post(
            reverse("spacemarches:character_complete", kwargs={"pk": self.sheet.pk}),
            {"status": "completed"},
        )
        self.assertEqual(resp.status_code, 302)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, GeneratedCharacter.STATUS_COMPLETED)
        self.assertIsNotNone(self.sheet.completed_at)

    def test_mark_draft_clears_timestamp(self):
        self.sheet.status = GeneratedCharacter.STATUS_COMPLETED
        self.sheet.completed_at = None
        self.sheet.save()
        # Need to be careful: the service sets completed_at on create; here we set manually
        from django.utils import timezone
        self.sheet.completed_at = timezone.now()
        self.sheet.save()

        resp = self.client.post(
            reverse("spacemarches:character_complete", kwargs={"pk": self.sheet.pk}),
            {"status": "draft"},
        )
        self.assertEqual(resp.status_code, 302)
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, GeneratedCharacter.STATUS_DRAFT)
        self.assertIsNone(self.sheet.completed_at)

    def test_public_toggle(self):
        resp = self.client.post(
            reverse("spacemarches:character_public_toggle", kwargs={"pk": self.sheet.pk}),
            {"public_view": "1"},
        )
        self.assertEqual(resp.status_code, 302)
        self.sheet.refresh_from_db()
        self.assertTrue(self.sheet.public_view)

        resp = self.client.post(
            reverse("spacemarches:character_public_toggle", kwargs={"pk": self.sheet.pk}),
            {"public_view": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.sheet.refresh_from_db()
        self.assertFalse(self.sheet.public_view)

    def test_save_sets_completed_for_new_sheets(self):
        from spacemarches.services.character_sync_service import save_generated_character
        new_sheet, created = save_generated_character(
            self.user,
            character_name="Fresh Sheet",
            raw_data={"type": "point-buy-exported", "pointBuy": {"name": {"en-US": "Fresh Sheet"}}},
        )
        self.assertTrue(created)
        refreshed = GeneratedCharacter.objects.get(pk=new_sheet.pk)
        self.assertEqual(refreshed.status, GeneratedCharacter.STATUS_COMPLETED)
        self.assertIsNotNone(refreshed.completed_at)

    def test_protection_unlock_endpoint(self):
        set_secret(self.sheet, "Puzzle?", "Answer-1")
        self.sheet.protection = GeneratedCharacter.PROTECTION_SECRET
        self.sheet.save()
        resp = self.client.post(
            reverse("spacemarches:character_protection", kwargs={"pk": self.sheet.pk}),
            {"action": "unlock", "answer": "Answer-1"},
        )
        self.assertEqual(resp.status_code, 302)
        # session unlocked
        resp = self.client.get(reverse("spacemarches:character_roster"))
        self.assertEqual(resp.status_code, 200)


class DossierDetailProtectionTests(TestCase):
    def setUp(self):
        import spacemarches.services.protection_service as ps
        self.ps = ps
        user = User.objects.create_user(username="owner2", password="pw12345!")
        self.owner = user
        st_user = User.objects.create_user(username="st2", password="pw12345!", is_st=True)
        self.st = st_user
        self.dossier = CharacterDossier.objects.create(
            user=user, character_name="Logged Dossier", slug="logged-dossier",
        )
        self.sheet = GeneratedCharacter.objects.create(
            user=user, dossier=self.dossier, character_name="Logged Sheet",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data={}, summary={}, status=GeneratedCharacter.STATUS_COMPLETED,
            public_view=True,
        )

    def test_security_log_records_st_access(self):
        # ST-only access is mediated through the review surface: the ST holder
        # views the owner's public review and the ST-only sheet renders.
        self.sheet.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.sheet.save()
        self.client.login(username="st2", password="pw12345!")
        self.client.get(reverse("spacemarches:dossier_review", kwargs={"slug": "logged-dossier"}))
        self.assertEqual(
            ProtectionAccessLog.objects.filter(
                target_kind="character", target_pk=self.sheet.pk, viewer__username="st2",
            ).count(),
            1,
        )

    def test_detail_page_seals_st_only_sheet_for_non_owner_admin(self):
        admin = User.objects.create_superuser(username="admin", password="pw12345!", email="a@b.c")
        self.sheet.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.sheet.save()
        self.client.login(username="admin", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": "logged-dossier"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sealed Sheet")
        self.assertNotContains(resp, "Logged Sheet")

    def test_detail_page_seals_secret_sheet_for_admin(self):
        admin = User.objects.create_superuser(username="admin2", password="pw12345!", email="a@b.c")
        self.sheet.protection = GeneratedCharacter.PROTECTION_SECRET
        ps_secret = self.ps
        ps_secret.set_secret(self.sheet, "Prompt?", "answer-1")
        self.sheet.save()
        self.client.login(username="admin2", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": "logged-dossier"}))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Logged Sheet")

    def test_owner_sees_security_log_panel(self):
        self.dossier.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.dossier.save()
        ProtectionAccessLog.objects.create(
            target_kind="dossier", target_pk=self.dossier.pk, owner=self.owner,
            viewer=self.st, protection_type=GeneratedCharacter.PROTECTION_ST_ONLY,
            note="Section view",
        )
        self.client.login(username="owner2", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": "logged-dossier"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Security Log")

    def test_owner_is_not_locked_out_of_own_dossier(self):
        self.dossier.protection = GeneratedCharacter.PROTECTION_SECRET
        ps_secret = self.ps
        ps_secret.set_secret(self.dossier, "Locked?", "S3cr3t")
        self.client.login(username="owner2", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": "logged-dossier"}))
        # the dossier page itself renders (with the protection panel), even though the
        # review surface below is secret-locked — the owner must not be locked out of
        # their own dossier management
        self.assertEqual(resp.status_code, 200)

    def test_owner_sees_sheet_level_security_log_even_when_dossier_unprotected(self):
        self.sheet.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.sheet.save()
        ProtectionAccessLog.objects.create(
            target_kind=ProtectionAccessLog.TARGET_CHARACTER,
            target_pk=self.sheet.pk,
            owner=self.owner,
            viewer=self.st,
            protection_type=GeneratedCharacter.PROTECTION_ST_ONLY,
            note="Section view",
        )
        self.client.login(username="owner2", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": "logged-dossier"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Security Log")
        self.assertContains(resp, "Character Sheet")

    def test_duplicate_dossier_slug_review_does_not_500_and_pk_route_disambiguates(self):
        other = User.objects.create_user(username="other_dupe", password="pw12345!")
        other_dossier = CharacterDossier.objects.create(
            user=other, character_name="Logged Dossier", slug="logged-dossier",
        )
        other_sheet = GeneratedCharacter.objects.create(
            user=other, dossier=other_dossier, character_name="Other Dupe Sheet",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data={}, summary={}, status=GeneratedCharacter.STATUS_COMPLETED,
            public_view=True,
        )
        slug_resp = self.client.get(reverse("spacemarches:dossier_review", kwargs={"slug": "logged-dossier"}))
        self.assertEqual(slug_resp.status_code, 200)

        pk_resp = self.client.get(reverse("spacemarches:dossier_review_by_id", kwargs={"pk": other_dossier.pk}))
        self.assertEqual(pk_resp.status_code, 200)
        self.assertContains(pk_resp, other_sheet.character_name)
        self.assertNotContains(pk_resp, self.sheet.character_name)

    def test_terminal_autosave_uses_canonical_source_system_and_dedup_cache(self):
        self.client.login(username="owner2", password="pw12345!")
        resp = self.client.get(reverse("spacemarches:meshnet"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "source_system: \"point_buy_v2\"")
        self.assertNotContains(resp, "source_system: \"point-buy-v2\"")
        self.assertContains(resp, "sm_autosave_hashes_v1")
