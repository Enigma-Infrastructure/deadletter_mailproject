"""Tests for server-side sensitive content screening and shared rate limiting."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from people.models import Person, Place
from .content_screening import screen_content
from .models import Letter, LetterConcept, LetterInstance, LetterRequest
from .ratelimit import check_rate_limit


class ContentScreeningUnitTests(TestCase):
    def test_clean_content_passes(self):
        is_restricted, reason = screen_content("Just a friendly note from a sea traveler heading to Maine.")
        self.assertFalse(is_restricted)
        self.assertEqual(reason, "")

    def test_phone_number_flagged(self):
        is_restricted, reason = screen_content("Call me at 617-555-0199 whenever you arrive.")
        self.assertTrue(is_restricted)
        self.assertEqual(reason, "phone_pattern_detected")

    def test_email_flagged(self):
        is_restricted, reason = screen_content("Send a letter response to sailor@example.com please.")
        self.assertTrue(is_restricted)
        self.assertEqual(reason, "email_pattern_detected")

    def test_ssn_flagged(self):
        is_restricted, reason = screen_content("Do not share 123-45-6789 with anyone.")
        self.assertTrue(is_restricted)
        self.assertEqual(reason, "ssn_pattern_detected")

    def test_external_link_flagged(self):
        is_restricted, reason = screen_content("Check out this suspicious site: https://phishing-scam.xyz/steal")
        self.assertTrue(is_restricted)
        self.assertEqual(reason, "external_link_flagged")

    def test_prohibited_terms_flagged(self):
        is_restricted, reason = screen_content("threat of swatting the location")
        self.assertTrue(is_restricted)
        self.assertEqual(reason, "prohibited_content_flagged")


class ScreeningAndRateLimitIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        User = get_user_model()
        self.writer = User.objects.create_user(
            username="screened-writer",
            email="writer@example.org",
            password="WriterPassword123!",
            is_active=True,
            participant_status="approved",
        )
        self.place = Place.objects.create(name="Tide Saloon", city="Gloucester", kind="bar")
        self.recipient = Person.objects.create(nickname="Nautilus", pirate_place=self.place, city="Gloucester")

    def test_intake_automatically_restricts_flagged_content(self):
        intake_url = reverse("request_a_letter")
        payload = {
            "nickname": "Nautilus",
            "pirate_address": "Tide Saloon",
            "city": "Gloucester",
            "write_about": "Call me immediately at 617-555-0144 for secret info.",
        }

        response = self.client.post(intake_url, payload)
        self.assertEqual(response.status_code, 200)

        # Verified request was flagged and restricted
        req = LetterRequest.objects.get(prompt=payload["write_about"])
        self.assertTrue(req.automatically_restricted)
        self.assertEqual(req.restriction_reason, "phone_pattern_detected")
        self.assertFalse(req.is_published)

    def test_desk_claim_automatically_restricts_flagged_body(self):
        concept = LetterConcept.objects.create(
            title="Clean Concept",
            write_prompt="Friendly prompt",
            destination_place=self.place,
            destination_city="Gloucester",
            created_for=self.recipient,
        )
        self.client.force_login(self.writer)
        claim_url = reverse("letter_write_claim", kwargs={"pk": concept.pk})

        claim_payload = {"body_text": "Check out my link at https://scam-store.com/buy-now for gifts!"}
        response = self.client.post(claim_url, claim_payload)
        self.assertEqual(response.status_code, 302)

        letter = Letter.objects.get(concept=concept)
        self.assertTrue(letter.automatically_restricted)
        self.assertEqual(letter.restriction_reason, "external_link_flagged")
        self.assertFalse(letter.is_published)
        self.assertIsNone(letter.finalized_at)

        instance = LetterInstance.objects.get(concept=concept)
        self.assertFalse(instance.is_public)
        self.assertEqual(instance.status, "created")

    def test_shared_rate_limiting_enforces_threshold(self):
        factory = RequestFactory()
        req = factory.post("/write/request/")
        req.user = self.writer

        # 3 calls with max 3 should pass, 4th fails
        self.assertTrue(check_rate_limit(req, "test_action", max_requests=3, window_seconds=60))
        self.assertTrue(check_rate_limit(req, "test_action", max_requests=3, window_seconds=60))
        self.assertTrue(check_rate_limit(req, "test_action", max_requests=3, window_seconds=60))
        self.assertFalse(check_rate_limit(req, "test_action", max_requests=3, window_seconds=60))
