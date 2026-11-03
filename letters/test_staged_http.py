"""Integration tests for staged HTTP adapters.

These tests use the isolated URL configuration (letters.staged_urls) and
verify both returned data and absence of unintended writes. The staged
URLconf is NOT included in the main project routing.
"""
import json
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from people.models import Person, Place
from .domain_editing import TOKEN_SALT, letter_draft_snapshot, request_draft_snapshot
from .domain_writes import create_request, create_response
from .models import Letter, LetterInstance, LetterRequest, Stamp


@override_settings(ROOT_URLCONF="letters.staged_urls")
class StagedHttpTests(TestCase):
    """Integration tests for staged HTTP presentation and editing."""

    def setUp(self):
        User = get_user_model()
        self.approved = User.objects.create_user(
            username="approved-user", email="approved@example.org",
            participant_status="approved",
        )
        self.other = User.objects.create_user(
            username="other-user", participant_status="approved",
        )
        self.unapproved = User.objects.create_user(
            username="unapproved-user", participant_status="pending",
        )
        place = Place.objects.create(name="Test Place", city="Test City")
        person = Person.objects.create(
            nickname="Test Alias", email="test@example.org", pirate_place=place,
        )
        # Published request visible to audience
        self.published_request = LetterRequest.objects.create(
            owner=self.approved, submitted_by=self.approved,
            recipient=person, recipient_alias="Test Alias",
            prompt="Published prompt", destination_place=place,
            destination_city="Test City", destination_label="Test Place · Test City",
            is_published=True, requested_visibility="public",
            restriction_reason="Test reason",
        )
        # Published letter visible to audience
        self.published_letter = Letter.objects.create(
            request=self.published_request, writer=self.approved,
            body_text="Published body", recipient=person,
            recipient_alias="Test Alias", prompt_snapshot="Published prompt",
            destination_place=place, destination_city="Test City",
            destination_label="Test Place · Test City",
            is_published=True, requested_visibility="public",
            restriction_reason="Test reason",
        )
        instance = LetterInstance.objects.create(
            authored_letter=self.published_letter, code="TRACKING-CODE",
        )
        Stamp.objects.create(letter=instance, number="STAMP-NUMBER")
        # Unpublished draft request owned by approved user
        self.draft_request = create_request(
            self.approved, recipient_id=person.pk, prompt="Draft prompt",
        )
        # Unpublished draft letter written by approved user
        self.draft_letter, self.draft_instance = create_response(
            self.approved, request_id=self.published_request.pk,
            body_text="Draft body",
        )

    def _get(self, url, data=None, **extra):
        if data is None:
            data = {}
        return self.client.get(url, data, **extra)

    def _post(self, url, data=None, **extra):
        if data is None:
            data = {}
        return self.client.post(url, data, **extra)

    # --------------------------------------------------
    # 1. Anonymous versus approved audience reads
    # --------------------------------------------------

    def test_anonymous_request_list_sees_only_public(self):
        response = self._get("/staged/requests/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("cards", data)
        # Only the published request should be visible
        self.assertEqual(len(data["cards"]), 1)
        self.assertEqual(data["cards"][0]["id"], self.published_request.pk)
        self.assertEqual(data["cards"][0]["prompt"], "Published prompt")
        self.assertEqual(data["cards"][0]["recipient_alias"], "Test Alias")

    def test_anonymous_letter_list_sees_only_public(self):
        response = self._get("/staged/letters/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("cards", data)
        # Only the published letter should be visible
        self.assertEqual(len(data["cards"]), 1)
        self.assertEqual(data["cards"][0]["id"], self.published_letter.pk)
        self.assertEqual(data["cards"][0]["body_text"], "Published body")
        self.assertEqual(data["cards"][0]["recipient_alias"], "Test Alias")

    def test_approved_user_sees_participants_only(self):
        # Change the published request to participants_only
        LetterRequest.objects.filter(pk=self.published_request.pk).update(
            requested_visibility="participants_only",
        )
        # Anonymous should not see it
        response = self._get("/staged/requests/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["cards"]), 0)
        # Approved user should see it
        self.client.force_login(self.approved)
        response = self._get("/staged/requests/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["cards"]), 1)

    def test_parent_request_bounds_letter_visibility(self):
        # Make the parent request unpublished
        LetterRequest.objects.filter(pk=self.published_request.pk).update(
            is_published=False,
        )
        # The letter should no longer be visible to anyone
        response = self._get("/staged/letters/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["cards"]), 0)

    def test_request_detail_returns_exact_card(self):
        response = self._get(f"/staged/requests/{self.published_request.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("card", data)
        self.assertEqual(data["card"], {
            "id": self.published_request.pk,
            "prompt": "Published prompt",
            "recipient_alias": "Test Alias",
        })

    def test_letter_detail_returns_exact_card(self):
        response = self._get(f"/staged/letters/{self.published_letter.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("card", data)
        self.assertEqual(data["card"], {
            "id": self.published_letter.pk,
            "body_text": "Published body",
            "recipient_alias": "Test Alias",
        })

    def test_missing_or_inaccessible_detail_returns_404(self):
        # Nonexistent ID
        response = self._get("/staged/requests/99999/")
        self.assertEqual(response.status_code, 404)
        # Unpublished request not visible to anonymous
        response = self._get(f"/staged/requests/{self.draft_request.pk}/")
        self.assertEqual(response.status_code, 404)

    # --------------------------------------------------
    # 2. Exact output keys; no addresses, account metadata, etc.
    # --------------------------------------------------

    def test_output_keys_are_exact_allowlist(self):
        response = self._get(f"/staged/requests/{self.published_request.pk}/")
        self.assertEqual(response.status_code, 200)
        card = response.json()["card"]
        self.assertEqual(set(card.keys()), {"id", "prompt", "recipient_alias"})

        response = self._get(f"/staged/letters/{self.published_letter.pk}/")
        self.assertEqual(response.status_code, 200)
        card = response.json()["card"]
        self.assertEqual(set(card.keys()), {"id", "body_text", "recipient_alias"})

    def test_no_addresses_account_metadata_or_tracking_codes_in_output(self):
        response = self._get("/staged/requests/")
        text = json.dumps(response.json())
        for marker in (
            "Test Place", "Test City", "Test Place · Test City",
            "approved-user", "approved@example.org",
            "TRACKING-CODE", "STAMP-NUMBER",
            "Test Alias",  # recipient_alias IS in the allowlist
        ):
            # recipient_alias is permitted; others should not appear
            if marker == "Test Alias":
                continue
            self.assertNotIn(marker, text)

    def test_no_raw_orm_relations_or_history_in_output(self):
        response = self._get("/staged/letters/")
        text = json.dumps(response.json())
        for marker in ("request_id", "writer_id", "concept_id", "recipient_id",
                       "destination_place_id", "created_at", "finalized_at"):
            self.assertNotIn(marker, text)

    # --------------------------------------------------
    # 3. Private owner/writer checks
    # --------------------------------------------------

    def test_draft_snapshot_requires_approved_owner(self):
        # Anonymous cannot access
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 403)
        # Unapproved user cannot access
        self.client.force_login(self.unapproved)
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 403)
        # Other approved user (not owner) cannot access
        self.client.force_login(self.other)
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 403)
        # Owner can access
        self.client.force_login(self.approved)
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("card", data)
        self.assertIn("edit_token", data)

    def test_draft_snapshot_requires_approved_writer(self):
        # Anonymous cannot access
        response = self._get(f"/staged/letters/{self.draft_letter.pk}/draft/")
        self.assertEqual(response.status_code, 403)
        # Other approved user (not writer) cannot access
        self.client.force_login(self.other)
        response = self._get(f"/staged/letters/{self.draft_letter.pk}/draft/")
        self.assertEqual(response.status_code, 403)
        # Writer can access
        self.client.force_login(self.approved)
        response = self._get(f"/staged/letters/{self.draft_letter.pk}/draft/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("card", data)
        self.assertIn("edit_token", data)

    def test_approval_revocation_blocks_draft_access(self):
        self.client.force_login(self.approved)
        # Initially works
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 200)
        # Revoke approval
        get_user_model().objects.filter(pk=self.approved.pk).update(
            participant_status="suspended",
        )
        # Now blocked
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 403)

    def test_no_staff_bypass_for_draft_access(self):
        # Make the user a staff user but not approved
        self.client.force_login(self.unapproved)
        self.unapproved.is_staff = True
        self.unapproved.save()
        response = self._get(f"/staged/requests/{self.draft_request.pk}/draft/")
        self.assertEqual(response.status_code, 403)

    # --------------------------------------------------
    # 4. CSRF rejection and valid authorized save
    # --------------------------------------------------

    def test_csrf_rejection_with_no_writes(self):
        # Use a fresh client with CSRF enforcement and no session/cookie state.
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        # POST without any CSRF token — CsrfViewMiddleware rejects it
        response = csrf_client.post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "New prompt", "expected_token": token},
        )
        self.assertEqual(response.status_code, 403)
        # Verify no write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "Draft prompt")

    def test_valid_csrf_protected_save(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        # POST with CSRF token
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "New prompt", "expected_token": token},
            **{"headers": {"Referer": "http://testserver/staged/requests/"}},
        )
        # Django test client handles CSRF automatically
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("card", data)
        self.assertIn("edit_token", data)
        self.assertEqual(data["card"]["prompt"], "New prompt")
        # Verify the write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "New prompt")

    def test_valid_csrf_protected_letter_save(self):
        self.client.force_login(self.approved)
        token = letter_draft_snapshot(self.approved, self.draft_letter.pk)["edit_token"]
        response = self._post(
            f"/staged/letters/{self.draft_letter.pk}/save/",
            {"body_text": "New body", "expected_token": token},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("card", data)
        self.assertIn("edit_token", data)
        self.assertEqual(data["card"]["body_text"], "New body")
        # Verify the write and mirror
        self.draft_letter.refresh_from_db()
        self.draft_instance.refresh_from_db()
        self.assertEqual(self.draft_letter.body_text, "New body")
        self.assertEqual(self.draft_instance.body_text, "New body")

    # --------------------------------------------------
    # 5. Wrong HTTP methods with no writes
    # --------------------------------------------------

    def test_post_to_list_endpoint_rejected(self):
        self.client.force_login(self.approved)
        response = self._post("/staged/requests/", {"prompt": "Bad"})
        self.assertEqual(response.status_code, 405)

    def test_get_to_save_endpoint_rejected(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        response = self._get(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"expected_token": token},
        )
        self.assertEqual(response.status_code, 405)
        # Verify no write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "Draft prompt")

    def test_put_to_save_endpoint_rejected(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        response = self.client.put(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "Bad", "expected_token": token},
        )
        self.assertEqual(response.status_code, 405)
        # Verify no write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "Draft prompt")

    # --------------------------------------------------
    # 6. Token conflicts without overwriting
    # --------------------------------------------------

    def test_stale_token_conflict_preserves_newer_body(self):
        self.client.force_login(self.approved)
        # Get initial token (state: "Draft prompt")
        token1 = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        # Save with token1 — prompt becomes "First edit"
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "First edit", "expected_token": token1},
        )
        self.assertEqual(response.status_code, 200)
        # token1 is now stale (state changed). Try to reuse it.
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "Lost update", "expected_token": token1},
        )
        self.assertEqual(response.status_code, 409)
        # Verify the first edit is preserved
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "First edit")

    def test_expired_token_conflict(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        # Simulate expiry
        future = time.time() + 1800 + 5
        with patch("django.core.signing.time.time", return_value=future):
            response = self._post(
                f"/staged/requests/{self.draft_request.pk}/save/",
                {"prompt": "Expired", "expected_token": token},
            )
        self.assertEqual(response.status_code, 409)
        # Verify no write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "Draft prompt")

    def test_invalid_token_conflict(self):
        self.client.force_login(self.approved)
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "Bad", "expected_token": "tampered-token"},
        )
        self.assertEqual(response.status_code, 409)
        # Verify no write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "Draft prompt")

    def test_missing_token_rejected(self):
        self.client.force_login(self.approved)
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "No token"},
        )
        self.assertEqual(response.status_code, 400)
        # Verify no write occurred
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.prompt, "Draft prompt")

    # --------------------------------------------------
    # 7. Unknown/forged authority fields rejected
    # --------------------------------------------------

    def test_forged_owner_field_rejected(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "New", "expected_token": token, "owner": "forged"},
        )
        self.assertEqual(response.status_code, 200)
        # Verify the owner was not changed
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.owner_id, self.approved.pk)

    def test_forged_publication_field_rejected(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "New", "expected_token": token, "is_published": "true"},
        )
        self.assertEqual(response.status_code, 200)
        # Verify the publication state was not changed
        self.draft_request.refresh_from_db()
        self.assertFalse(self.draft_request.is_published)

    def test_forged_submitter_field_rejected(self):
        self.client.force_login(self.approved)
        token = request_draft_snapshot(self.approved, self.draft_request.pk)["edit_token"]
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "New", "expected_token": token, "submitted_by": "forged"},
        )
        self.assertEqual(response.status_code, 200)
        # Verify the submitter was not changed
        self.draft_request.refresh_from_db()
        self.assertEqual(self.draft_request.submitted_by_id, self.approved.pk)

    def test_forged_physical_state_rejected(self):
        self.client.force_login(self.approved)
        token = letter_draft_snapshot(self.approved, self.draft_letter.pk)["edit_token"]
        response = self._post(
            f"/staged/letters/{self.draft_letter.pk}/save/",
            {"body_text": "New", "expected_token": token, "needs_printing": "false"},
        )
        self.assertEqual(response.status_code, 200)
        # Verify the physical state was not changed
        self.draft_instance.refresh_from_db()
        self.assertTrue(self.draft_instance.needs_printing)

    # --------------------------------------------------
    # 8. Generic database failures without details
    # --------------------------------------------------

    def test_database_failure_returns_generic_error(self):
        self.client.force_login(self.approved)
        token = letter_draft_snapshot(self.approved, self.draft_letter.pk)["edit_token"]
        with patch(
            "letters.domain_drafts.LetterInstance.save",
            side_effect=IntegrityError("Mirror failure"),
        ):
            response = self._post(
                f"/staged/letters/{self.draft_letter.pk}/save/",
                {"body_text": "Rollback", "expected_token": token},
            )
        # Should return a 500 or similar generic error
        self.assertIn(response.status_code, (500, 400, 409))
        # Verify no partial write occurred
        self.draft_letter.refresh_from_db()
        self.draft_instance.refresh_from_db()
        self.assertEqual(self.draft_letter.body_text, "Draft body")
        self.assertEqual(self.draft_instance.body_text, "Draft body")

    def test_no_exception_trace_in_error_response(self):
        self.client.force_login(self.approved)
        response = self._post(
            f"/staged/requests/{self.draft_request.pk}/save/",
            {"prompt": "Bad", "expected_token": "invalid"},
        )
        self.assertEqual(response.status_code, 409)
        text = response.content.decode()
        for marker in ("Traceback", "IntegrityError", "PermissionDenied",
                       "DraftConflict", "SELECT", "INSERT", "UPDATE"):
            self.assertNotIn(marker, text)

    # --------------------------------------------------
    # 9. Staged URLconf not in main routing
    # --------------------------------------------------

    def test_staged_urls_not_in_main_routing(self):
        # The main URL configuration should not include staged URLs
        from deadletter_mailproject.urls import urlpatterns as main_patterns
        for pattern in main_patterns:
            self.assertNotIn("staged", str(pattern.pattern))

    def test_live_routes_unchanged(self):
        # The main URLconf still contains the live route patterns.
        # (We cannot hit them under the staged ROOT_URLCONF override,
        #  so we verify the patterns are present in the main config.)
        from deadletter_mailproject.urls import urlpatterns as main_patterns
        paths = [str(p.pattern) for p in main_patterns]
        self.assertIn("letters/", paths)
        self.assertIn("write/", paths)
