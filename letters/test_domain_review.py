"""Tests for content review, publication approval, and finalization services."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from people.models import Person, Place
from .domain_access import readable_letters, readable_requests
from .domain_review import (
    pending_review_letters,
    pending_review_requests,
    publish_letter,
    publish_request,
    restrict_content,
)
from .domain_writes import create_request, create_response
from .models import Letter, LetterInstance, LetterRequest


class DomainReviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_reviewer = User.objects.create_user(
            username='reviewer', password='password123', is_staff=True, participant_status='approved'
        )
        self.participant = User.objects.create_user(
            username='participant', password='password123', participant_status='approved'
        )
        self.writer = User.objects.create_user(
            username='writer', password='password123', participant_status='approved'
        )

        place = Place.objects.create(name='Social Camp', city='Portland')
        person = Person.objects.create(nickname='Wanderer', pirate_place=place, city='Portland')

        # Create unpublished review draft request
        self.req = create_request(
            self.participant,
            recipient_id=person.pk,
            prompt='Prompt needing review',
            requested_visibility='public',
        )

    def test_reviewer_authorization_required(self):
        # Non-staff participant denied
        with self.assertRaises(PermissionDenied):
            publish_request(self.participant, self.req.pk)

        # Unauthenticated user denied
        with self.assertRaises(PermissionDenied):
            publish_request(None, self.req.pk)

        # Inactive staff denied
        inactive_staff = get_user_model().objects.create_user(
            username='inactive_staff', is_staff=True, is_active=False
        )
        with self.assertRaises(PermissionDenied):
            publish_request(inactive_staff, self.req.pk)

    def test_publish_request_success_and_allowlist(self):
        self.assertFalse(self.req.is_published)
        self.assertTrue(self.req.automatically_restricted)
        self.assertEqual(self.req.restriction_reason, 'review_required')

        card = publish_request(self.staff_reviewer, self.req.pk)
        self.assertEqual(set(card.keys()), {'id', 'prompt', 'recipient_alias'})
        self.assertEqual(card['id'], self.req.pk)
        self.assertEqual(card['prompt'], 'Prompt needing review')

        self.req.refresh_from_db()
        self.assertTrue(self.req.is_published)
        self.assertFalse(self.req.automatically_restricted)
        self.assertEqual(self.req.restriction_reason, '')

        # Now appears in public readable requests
        public_readable = readable_requests(None)
        self.assertIn(self.req, public_readable)

    def test_publish_request_nonexistent_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            publish_request(self.staff_reviewer, 99999)

    def test_publish_letter_requires_published_parent_request(self):
        # Publish parent request first to create response
        publish_request(self.staff_reviewer, self.req.pk)
        letter, instance = create_response(
            self.writer, request_id=self.req.pk, body_text='Authored letter text'
        )
        self.assertFalse(letter.is_published)
        self.assertIsNone(letter.finalized_at)
        self.assertFalse(instance.is_public)
        self.assertEqual(instance.status, 'created')

        # Unpublish parent request to test invariant
        restrict_content(
            self.staff_reviewer, 'request', self.req.pk, reason='temporarily_hidden'
        )
        self.req.refresh_from_db()
        self.assertFalse(self.req.is_published)

        with self.assertRaises(ValidationError) as ctx:
            publish_letter(self.staff_reviewer, letter.pk)
        self.assertIn('originating request is unpublished', str(ctx.exception))

        # Re-publish parent request, now letter publication succeeds
        publish_request(self.staff_reviewer, self.req.pk)
        card = publish_letter(self.staff_reviewer, letter.pk)
        self.assertEqual(set(card.keys()), {'id', 'body_text', 'recipient_alias'})
        self.assertEqual(card['body_text'], 'Authored letter text')

        letter.refresh_from_db()
        instance.refresh_from_db()
        self.assertTrue(letter.is_published)
        self.assertFalse(letter.automatically_restricted)
        self.assertIsNotNone(letter.finalized_at)

        # Linked physical instance is unlocked for printing
        self.assertTrue(instance.is_public)
        self.assertEqual(instance.status, 'waiting_print')

        # Now readable by audience
        self.assertIn(letter, readable_letters(None))

    def test_restrict_content_and_hide_physical_copies(self):
        publish_request(self.staff_reviewer, self.req.pk)
        letter, instance = create_response(
            self.writer, request_id=self.req.pk, body_text='Text to restrict'
        )
        publish_letter(self.staff_reviewer, letter.pk)

        # Restrict the letter
        restrict_content(
            self.staff_reviewer, 'letter', letter.pk, reason='pii_detected'
        )
        letter.refresh_from_db()
        instance.refresh_from_db()

        self.assertFalse(letter.is_published)
        self.assertTrue(letter.automatically_restricted)
        self.assertEqual(letter.restriction_reason, 'pii_detected')
        self.assertFalse(instance.is_public)

        # Inaccessible to audience
        self.assertNotIn(letter, readable_letters(None))

    def test_pending_review_queries(self):
        publish_request(self.staff_reviewer, self.req.pk)
        letter, _ = create_response(
            self.writer, request_id=self.req.pk, body_text='Pending letter text'
        )

        # Another unreviewed request
        place2 = Place.objects.create(name='Coffee Shop', city='Seattle')
        person2 = Person.objects.create(nickname='Explorer', pirate_place=place2, city='Seattle')
        req2 = create_request(self.participant, recipient_id=person2.pk, prompt='Second unreviewed')

        pending_reqs = pending_review_requests(self.staff_reviewer)
        req_ids = [r['id'] for r in pending_reqs]
        self.assertIn(req2.pk, req_ids)
        self.assertNotIn(self.req.pk, req_ids)  # self.req was already published

        pending_lets = pending_review_letters(self.staff_reviewer)
        let_ids = [l['id'] for l in pending_lets]
        self.assertIn(letter.pk, let_ids)
