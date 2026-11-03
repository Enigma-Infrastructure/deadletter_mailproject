"""Tests for domain privacy enforcement across reader, desk, carry, API, and account views."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from people.models import Person, Place
from .models import Letter, LetterConcept, LetterInstance, LetterRequest, Stamp


class DomainViewsCutoverTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.approved_user = User.objects.create_user(
            username="approved-courier",
            email="courier@example.org",
            password="Password123!",
            is_active=True,
            participant_status="approved",
        )
        self.pending_user = User.objects.create_user(
            username="pending-reader",
            email="pending@example.org",
            password="Password123!",
            is_active=True,
            participant_status="pending",
        )

        self.place = Place.objects.create(name="Starlight Lounge", city="Salem", kind="bar")
        self.recipient = Person.objects.create(nickname="Orion", pirate_place=self.place, city="Salem")

    def create_letter_bundle(self, *, visibility="public", published=True, restricted=False, status="traveling", body="Test letter body"):
        concept = LetterConcept.objects.create(
            title="Concept for Orion",
            write_prompt="Tell a tale",
            destination_place=self.place,
            destination_city="Salem",
            created_for=self.recipient,
        )
        req = LetterRequest.objects.create(
            prompt=concept.write_prompt,
            recipient=self.recipient,
            recipient_alias="Orion",
            destination_place=self.place,
            destination_city="Salem",
            concept=concept,
            legacy_source=concept,
            requested_visibility=visibility,
            automatically_restricted=restricted,
            is_published=published,
            is_open=False,
        )
        letter = Letter.objects.create(
            request=req,
            concept=concept,
            body_text=body,
            recipient=self.recipient,
            recipient_alias="Orion",
            destination_place=self.place,
            destination_city="Salem",
            requested_visibility=visibility,
            automatically_restricted=restricted,
            is_published=published,
        )
        instance = LetterInstance.objects.create(
            authored_letter=letter,
            concept=concept,
            recipient=self.recipient,
            body_text=body,
            status=status,
            needs_printing=False,
            is_public=published and not restricted,
        )
        stamp = Stamp.objects.create(letter=instance, is_active=True)
        return req, letter, instance, stamp

    def test_read_lists_enforce_audience_and_moderation(self):
        # 1. Public published
        _, _, pub_inst, _ = self.create_letter_bundle(
            visibility="public", published=True, body="PUBLIC-READABLE-MARKER"
        )
        # 2. Participants only published
        _, _, part_inst, _ = self.create_letter_bundle(
            visibility="participants_only", published=True, body="PARTICIPANTS-ONLY-MARKER"
        )
        # 3. Unpublished draft
        _, _, unpub_inst, _ = self.create_letter_bundle(
            visibility="public", published=False, body="UNPUBLISHED-MARKER"
        )
        # 4. Restricted letter
        _, _, rest_inst, _ = self.create_letter_bundle(
            visibility="public", published=True, restricted=True, body="RESTRICTED-MARKER"
        )

        for url_name in ("letter_read_list", "desk_read_list"):
            url = reverse(url_name)

            # Anonymous view
            self.client.logout()
            anon_resp = self.client.get(url)
            self.assertEqual(anon_resp.status_code, 200)
            self.assertContains(anon_resp, "PUBLIC-READABLE-MARKER")
            self.assertNotContains(anon_resp, "PARTICIPANTS-ONLY-MARKER")
            self.assertNotContains(anon_resp, "UNPUBLISHED-MARKER")
            self.assertNotContains(anon_resp, "RESTRICTED-MARKER")

            # Pending (unapproved) user view
            self.client.force_login(self.pending_user)
            pending_resp = self.client.get(url)
            self.assertEqual(pending_resp.status_code, 200)
            self.assertContains(pending_resp, "PUBLIC-READABLE-MARKER")
            self.assertNotContains(pending_resp, "PARTICIPANTS-ONLY-MARKER")

            # Approved participant view
            self.client.force_login(self.approved_user)
            approved_resp = self.client.get(url)
            self.assertEqual(approved_resp.status_code, 200)
            self.assertContains(approved_resp, "PUBLIC-READABLE-MARKER")
            self.assertContains(approved_resp, "PARTICIPANTS-ONLY-MARKER")
            self.assertNotContains(approved_resp, "UNPUBLISHED-MARKER")
            self.assertNotContains(approved_resp, "RESTRICTED-MARKER")

    def test_letter_public_page_gates_audience_and_shields_address(self):
        # 1. Participants-only letter
        _, _, part_inst, _ = self.create_letter_bundle(
            visibility="participants_only", published=True, body="SECRET-SOCIETY-TEXT"
        )
        part_url = reverse("letter_public", kwargs={"code": part_inst.code})

        # Anonymous gets 404
        self.assertEqual(self.client.get(part_url).status_code, 404)

        # Pending user gets 404
        self.client.force_login(self.pending_user)
        self.assertEqual(self.client.get(part_url).status_code, 404)

        # Approved participant gets 200 and sees address
        self.client.force_login(self.approved_user)
        approved_resp = self.client.get(part_url)
        self.assertEqual(approved_resp.status_code, 200)
        self.assertContains(approved_resp, "SECRET-SOCIETY-TEXT")
        self.assertContains(approved_resp, "Starlight Lounge")

        # 2. Public letter: address shielded for anonymous, visible for approved
        _, _, pub_inst, _ = self.create_letter_bundle(
            visibility="public", published=True, body="OPEN-TOWN-TEXT"
        )
        pub_url = reverse("letter_public", kwargs={"code": pub_inst.code})

        self.client.logout()
        anon_pub_resp = self.client.get(pub_url)
        self.assertEqual(anon_pub_resp.status_code, 200)
        self.assertContains(anon_pub_resp, "OPEN-TOWN-TEXT")
        self.assertContains(anon_pub_resp, "Social destination address visible to approved participants")
        self.assertNotContains(anon_pub_resp, "Starlight Lounge")

        self.client.force_login(self.approved_user)
        app_pub_resp = self.client.get(pub_url)
        self.assertEqual(app_pub_resp.status_code, 200)
        self.assertContains(app_pub_resp, "Starlight Lounge")

    def test_carry_list_and_api_exclude_unpublished_or_restricted_letters(self):
        # Active published traveling letter
        _, _, active_inst, _ = self.create_letter_bundle(
            published=True, restricted=False, status="traveling", body="ACTIVE-CARRIER-BODY"
        )
        # Restricted traveling letter
        _, _, rest_inst, _ = self.create_letter_bundle(
            published=True, restricted=True, status="traveling", body="RESTRICTED-CARRIER-BODY"
        )

        carry_resp = self.client.get(reverse("carry_list"))
        self.assertEqual(carry_resp.status_code, 200)
        self.assertContains(carry_resp, active_inst.code)
        self.assertNotContains(carry_resp, rest_inst.code)

        api_resp = self.client.get(reverse("letters_in_my_area_api"))
        self.assertEqual(api_resp.status_code, 200)
        api_data = api_resp.json()
        codes = [item["code"] for item in api_data]
        self.assertIn(active_inst.code, codes)
        self.assertNotIn(rest_inst.code, codes)

    def test_writing_desk_excludes_restricted_and_closed_concepts(self):
        # Open concept
        open_concept = LetterConcept.objects.create(
            title="Open Concept", write_prompt="Available prompt", created_for=self.recipient
        )
        LetterRequest.objects.create(
            prompt=open_concept.write_prompt,
            concept=open_concept,
            legacy_source=open_concept,
            is_open=True,
            is_published=True,
            automatically_restricted=False,
        )

        # Restricted concept
        rest_concept = LetterConcept.objects.create(
            title="Restricted Concept", write_prompt="Spam prompt", created_for=self.recipient
        )
        LetterRequest.objects.create(
            prompt=rest_concept.write_prompt,
            concept=rest_concept,
            legacy_source=rest_concept,
            is_open=True,
            is_published=False,
            automatically_restricted=True,
        )

        # Closed concept
        closed_concept = LetterConcept.objects.create(
            title="Closed Concept", write_prompt="Finished prompt", created_for=self.recipient
        )
        LetterRequest.objects.create(
            prompt=closed_concept.write_prompt,
            concept=closed_concept,
            legacy_source=closed_concept,
            is_open=False,
            is_published=True,
            automatically_restricted=False,
        )

        for route in ("write_read_home", "letter_write_queue"):
            resp = self.client.get(reverse(route))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Open Concept")
            self.assertNotContains(resp, "Restricted Concept")
            self.assertNotContains(resp, "Closed Concept")

    def test_participant_status_displays_submissions_and_letters(self):
        self.client.force_login(self.approved_user)

        # Create user owned request
        req = LetterRequest.objects.create(
            prompt="My personal request prompt",
            recipient=self.recipient,
            recipient_alias="Orion",
            owner=self.approved_user,
            submitted_by=self.approved_user,
            is_published=True,
            is_open=True,
        )

        # Create user written letter
        let = Letter.objects.create(
            request=req,
            body_text="My personal authored letter text",
            writer=self.approved_user,
            recipient=self.recipient,
            recipient_alias="Orion",
            is_published=True,
        )
        LetterInstance.objects.create(
            authored_letter=let,
            recipient=self.recipient,
            body_text=let.body_text,
            status="traveling",
            is_public=True,
        )

        status_resp = self.client.get(reverse("participant_status"))
        self.assertEqual(status_resp.status_code, 200)
        self.assertContains(status_resp, "My Letter Requests")
        self.assertContains(status_resp, "My personal request prompt")
        self.assertContains(status_resp, "My Authored Letters")
        self.assertContains(status_resp, "My personal authored letter text")
