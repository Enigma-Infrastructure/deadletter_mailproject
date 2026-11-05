"""End-to-end integration tests for user workflow cutover.

Tests:
1. Public Intake (/write/request/) -> Dual-writes LetterConcept and LetterRequest.
2. Desk Claim (/letters/write/claim/<id>/) -> Creates Letter, closes LetterRequest, creates LetterInstance.
3. Print Queue (/letters/print/queue/) -> Surfaces claimed LetterInstance ready for printing/stamping.
4. Review Queue (/letters/review/queue/) -> Staff moderation, approval, restriction, and publication cascade.
5. Admin Hub (/admin/hub/) -> Contains links to moderation and print queues.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from people.models import Person, Place
from .domain_review import restrict_content
from .models import Letter, LetterConcept, LetterInstance, LetterRequest, Stamp


class WorkflowIntegrationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            username="staff-moderator",
            email="staff@example.org",
            password="StaffPassword123!",
            is_staff=True,
            is_active=True,
            participant_status="approved",
        )
        self.regular_user = User.objects.create_user(
            username="regular-writer",
            email="writer@example.org",
            password="WriterPassword123!",
            is_active=True,
            participant_status="approved",
        )

    def test_public_intake_creates_both_concept_and_domain_request(self):
        intake_url = reverse("request_a_letter")
        payload = {
            "nickname": "Captain Bluebeard",
            "pirate_address": "Salty Dog Saloon",
            "pirate_place_kind": "bar",
            "city": "Port Royal",
            "write_about": "Seeking old sea tales and nautical maps.",
        }

        response = self.client.post(intake_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "people/request_thanks.html")

        # 1. Verify Person and Place
        person = Person.objects.get(nickname="Captain Bluebeard")
        place = Place.objects.get(name="Salty Dog Saloon", city="Port Royal")
        self.assertEqual(person.pirate_place, place)

        # 2. Verify legacy LetterConcept
        concept = LetterConcept.objects.get(created_for=person)
        self.assertEqual(concept.write_prompt, "Seeking old sea tales and nautical maps.")
        self.assertEqual(concept.destination_place, place)
        self.assertEqual(concept.destination_city, "Port Royal")

        # 3. Verify domain LetterRequest dual-write
        letter_req = LetterRequest.objects.get(recipient=person)
        self.assertEqual(letter_req.prompt, "Seeking old sea tales and nautical maps.")
        self.assertEqual(letter_req.recipient_alias, "Captain Bluebeard")
        self.assertEqual(letter_req.destination_place, place)
        self.assertEqual(letter_req.destination_city, "Port Royal")
        self.assertEqual(letter_req.destination_label, "Salty Dog Saloon · Port Royal")
        self.assertEqual(letter_req.concept, concept)
        self.assertEqual(letter_req.legacy_source, concept)
        self.assertTrue(letter_req.is_published)
        self.assertTrue(letter_req.is_open)
        self.assertFalse(letter_req.automatically_restricted)

    def test_desk_claim_creates_letter_and_physical_instance_and_closes_request(self):
        # Seed an intake concept + request
        place = Place.objects.create(name="Lantern Cafe", city="Somerville", kind="cafe")
        person = Person.objects.create(nickname="Luna", pirate_place=place, city="Somerville")
        concept = LetterConcept.objects.create(
            title="Letter for Luna",
            write_prompt="Tell me about star gazing.",
            destination_place=place,
            destination_city="Somerville",
            created_for=person,
        )
        letter_req = LetterRequest.objects.create(
            prompt=concept.write_prompt,
            recipient=person,
            recipient_alias="Luna",
            destination_place=place,
            destination_city="Somerville",
            destination_label="Lantern Cafe · Somerville",
            concept=concept,
            legacy_source=concept,
            requested_visibility="public",
            is_published=True,
            is_open=True,
        )

        claim_url = reverse("letter_write_claim", kwargs={"pk": concept.pk})

        # Claim as regular user
        self.client.force_login(self.regular_user)
        claim_payload = {"body_text": "The stars in the northern sky shine the brightest tonight."}
        response = self.client.post(claim_url, claim_payload)

        # Expect redirect to confirmation
        self.assertEqual(response.status_code, 302)
        instance = LetterInstance.objects.get(concept=concept)
        self.assertEqual(response.url, reverse("letter_write_confirm", kwargs={"code": instance.code}))

        # Verify domain Letter was created
        letter = Letter.objects.get(concept=concept)
        self.assertEqual(letter.request, letter_req)
        self.assertEqual(letter.writer, self.regular_user)
        self.assertEqual(letter.body_text, claim_payload["body_text"])
        self.assertEqual(letter.recipient, person)
        self.assertEqual(letter.recipient_alias, "Luna")
        self.assertTrue(letter.is_published)
        self.assertIsNotNone(letter.finalized_at)

        # Verify LetterRequest was closed
        letter_req.refresh_from_db()
        self.assertFalse(letter_req.is_open)

        # Verify physical LetterInstance
        self.assertEqual(instance.authored_letter, letter)
        self.assertEqual(instance.status, "waiting_print")
        self.assertTrue(instance.needs_printing)
        self.assertTrue(instance.is_public)
        self.assertEqual(instance.created_by, self.regular_user)

        # Verify concept no longer appears in write queue
        queue_resp = self.client.get(reverse("letter_write_queue"))
        self.assertNotContains(queue_resp, concept.title)

    def test_claimed_letter_surfaces_in_print_pipeline_and_can_be_printed(self):
        place = Place.objects.create(name="Anchor Bookshop", city="Boston", kind="bookstore")
        person = Person.objects.create(nickname="Reader", pirate_place=place, city="Boston")
        concept = LetterConcept.objects.create(
            title="Letter for Reader",
            destination_place=place,
            destination_city="Boston",
            created_for=person,
        )
        letter_req = LetterRequest.objects.create(
            prompt="Books to read",
            recipient=person,
            recipient_alias="Reader",
            concept=concept,
            is_published=True,
            is_open=False,
        )
        letter = Letter.objects.create(
            request=letter_req,
            concept=concept,
            body_text="Read Moby Dick.",
            recipient=person,
            recipient_alias="Reader",
            is_published=True,
        )
        instance = LetterInstance.objects.create(
            authored_letter=letter,
            concept=concept,
            recipient=person,
            body_text=letter.body_text,
            status="waiting_print",
            needs_printing=True,
            is_public=True,
        )

        # Non-staff cannot access print queue
        self.client.force_login(self.regular_user)
        self.assertEqual(self.client.get(reverse("print_queue")).status_code, 302)

        # Staff can access print queue
        self.client.force_login(self.staff_user)
        queue_resp = self.client.get(reverse("print_queue"))
        self.assertEqual(queue_resp.status_code, 200)
        self.assertContains(queue_resp, instance.code)
        self.assertContains(queue_resp, "Reader")

        # Confirm print batch
        confirm_resp = self.client.post(reverse("print_confirm"), {"letters": [instance.pk]})
        self.assertEqual(confirm_resp.status_code, 302)

        instance.refresh_from_db()
        self.assertEqual(instance.status, "waiting_carrier")
        self.assertFalse(instance.needs_printing)
        self.assertIsNotNone(instance.printed_at)
        self.assertTrue(Stamp.objects.filter(letter=instance, is_active=True).exists())

    def test_review_queue_staff_authorization_and_moderation_actions(self):
        # 1. Unauthenticated or non-staff redirected
        review_url = reverse("letter_review_queue")
        anon_resp = self.client.get(review_url)
        self.assertEqual(anon_resp.status_code, 302)

        self.client.force_login(self.regular_user)
        user_resp = self.client.get(review_url)
        self.assertEqual(user_resp.status_code, 302)

        # 2. Staff user can view queue
        self.client.force_login(self.staff_user)
        get_resp = self.client.get(review_url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertTemplateUsed(get_resp, "letters/review_queue.html")

        # 3. Create restricted request and letter
        person = Person.objects.create(nickname="Suspicious User", city="Nowhere")
        req = LetterRequest.objects.create(
            prompt="Spam prompt needing review",
            recipient=person,
            recipient_alias="Suspicious User",
            requested_visibility="public",
            is_published=False,
            automatically_restricted=True,
            restriction_reason="review_required",
        )
        letter = Letter.objects.create(
            request=req,
            body_text="Letter with questionable content",
            recipient=person,
            recipient_alias="Suspicious User",
            requested_visibility="public",
            is_published=False,
            automatically_restricted=True,
            restriction_reason="review_required",
        )
        instance = LetterInstance.objects.create(
            authored_letter=letter,
            recipient=person,
            body_text=letter.body_text,
            status="created",
            is_public=False,
            needs_printing=True,
        )

        # Queue surfaces restricted items
        queue_content = self.client.get(review_url)
        self.assertContains(queue_content, "Spam prompt needing review")
        self.assertContains(queue_content, "Letter with questionable content")

        # Approve request
        app_req_resp = self.client.post(
            review_url,
            {"action": "approve_request", "record_id": str(req.pk)},
        )
        self.assertEqual(app_req_resp.status_code, 302)
        req.refresh_from_db()
        self.assertTrue(req.is_published)
        self.assertFalse(req.automatically_restricted)

        # Approve letter -> cascades to physical instance (is_public=True, status='waiting_print')
        app_let_resp = self.client.post(
            review_url,
            {"action": "approve_letter", "record_id": str(letter.pk)},
        )
        self.assertEqual(app_let_resp.status_code, 302)
        letter.refresh_from_db()
        self.assertTrue(letter.is_published)
        self.assertFalse(letter.automatically_restricted)
        self.assertIsNotNone(letter.finalized_at)

        instance.refresh_from_db()
        self.assertTrue(instance.is_public)
        self.assertEqual(instance.status, "waiting_print")

        # Restrict letter -> cascades is_public=False to instance
        rest_let_resp = self.client.post(
            review_url,
            {"action": "restrict_letter", "record_id": str(letter.pk), "reason": "Rule violation"},
        )
        self.assertEqual(rest_let_resp.status_code, 302)
        letter.refresh_from_db()
        self.assertFalse(letter.is_published)
        self.assertTrue(letter.automatically_restricted)
        self.assertEqual(letter.restriction_reason, "Rule violation")

        instance.refresh_from_db()
        self.assertFalse(instance.is_public)

    def test_admin_hub_surfaces_review_and_print_pipeline(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("admin_hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Production and Review Pipeline")
        self.assertContains(response, reverse("letter_review_queue"))
        self.assertContains(response, reverse("print_queue"))

    def test_desk_claim_on_backfilled_concept_re_uses_request_and_publishes(self):
        place = Place.objects.create(name="Historical Tavern", city="Newport", kind="bar")
        person = Person.objects.create(nickname="OldTimer", pirate_place=place, city="Newport")
        concept = LetterConcept.objects.create(
            title="Backfilled Letter",
            write_prompt="Reminiscing old harbor days.",
            destination_place=place,
            destination_city="Newport",
            created_for=person,
        )
        # Emulate historical backfill (where legacy_source was set, but concept was null, and is_published was False)
        backfilled_req = LetterRequest.objects.create(
            prompt=concept.write_prompt,
            recipient=person,
            recipient_alias="OldTimer",
            destination_place=place,
            destination_city="Newport",
            destination_label="Historical Tavern · Newport",
            legacy_source=concept,
            concept=None,
            is_published=False,
            is_open=True,
        )

        claim_url = reverse("letter_write_claim", kwargs={"pk": concept.pk})
        self.client.force_login(self.regular_user)
        response = self.client.post(claim_url, {"body_text": "Here is a story of the high seas."})
        self.assertEqual(response.status_code, 302)

        # Ensure no duplicate LetterRequest was created
        self.assertEqual(LetterRequest.objects.filter(legacy_source=concept).count(), 1)
        backfilled_req.refresh_from_db()
        self.assertFalse(backfilled_req.is_open)
        self.assertTrue(backfilled_req.is_published)
        self.assertEqual(backfilled_req.concept, concept)

        # Authored letter and physical copy exist
        letter = Letter.objects.get(request=backfilled_req)
        self.assertEqual(letter.body_text, "Here is a story of the high seas.")
        self.assertTrue(letter.is_published)
        instance = LetterInstance.objects.get(authored_letter=letter)
        self.assertTrue(instance.is_public)
        self.assertEqual(instance.status, "waiting_print")
