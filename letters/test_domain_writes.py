from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase

from people.models import Person, Place
from .domain_writes import create_request, create_response
from .models import Letter, LetterConcept, LetterInstance, LetterRequest, Stamp


class DomainWriteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner', participant_status='approved')
        self.writer = User.objects.create_user(username='writer', participant_status='approved')
        self.place = Place.objects.create(name='Original place', city='Original city')
        self.person = Person.objects.create(nickname='Original alias', pirate_place=self.place)
        self.parent = LetterRequest.objects.create(owner=self.owner, submitted_by=self.owner,
            recipient=self.person, recipient_alias='Saved alias', destination_place=self.place,
            destination_city='Saved city', destination_label='Saved destination', prompt='Saved prompt',
            is_published=True, requested_visibility='participants_only')

    def counts(self):
        return (LetterRequest.objects.count(), Letter.objects.count(), LetterInstance.objects.count(), LetterConcept.objects.count(), Stamp.objects.count())

    def test_request_attribution_snapshots_and_review_defaults(self):
        request = create_request(self.writer, recipient_id=self.person.pk, prompt='  Exact prompt  ')
        self.assertEqual(request.owner_id, self.writer.pk)
        self.assertEqual(request.submitted_by_id, self.writer.pk)
        self.assertEqual(request.prompt, '  Exact prompt  ')
        self.assertEqual(request.recipient_alias, 'Original alias')
        self.assertEqual(request.destination_label, 'Original place · Original city')
        self.assertEqual(request.requested_visibility, 'public')
        self.assertTrue(request.automatically_restricted)
        self.assertEqual(request.restriction_reason, 'review_required')
        self.assertFalse(request.is_published)
        self.assertTrue(request.is_open)
        self.assertIsNone(request.legacy_source_id)
        self.assertIsNone(request.concept_id)

    def test_response_pair_uses_saved_request_not_changed_profile(self):
        self.person.nickname = 'Changed alias'
        self.person.save()
        self.place.name = 'Changed place'
        self.place.save()
        letter, instance = create_response(self.writer, request_id=self.parent.pk, body_text='  Exact body\n')
        self.assertEqual(letter.writer_id, self.writer.pk)
        self.assertNotEqual(letter.writer_id, self.parent.owner_id)
        self.assertEqual(letter.prompt_snapshot, 'Saved prompt')
        self.assertEqual(letter.recipient_alias, 'Saved alias')
        self.assertEqual(letter.destination_label, 'Saved destination')
        self.assertEqual(letter.destination_city, 'Saved city')
        self.assertEqual(letter.body_text, '  Exact body\n')
        self.assertEqual(instance.body_text, letter.body_text)
        self.assertEqual(instance.authored_letter_id, letter.pk)
        self.assertEqual(instance.created_by_id, self.writer.pk)
        self.assertIsNone(instance.concept_id)
        self.assertFalse(instance.is_public)
        self.assertEqual(instance.status, 'created')
        self.assertTrue(instance.needs_printing)
        self.assertIsNone(instance.printed_at)
        self.assertFalse(letter.is_published)
        self.assertTrue(letter.automatically_restricted)
        self.assertIsNone(letter.finalized_at)
        self.parent.refresh_from_db()
        self.assertTrue(self.parent.is_open)
        self.assertEqual(Stamp.objects.count(), 0)

    def test_identical_calls_are_distinct_submissions_not_text_deduplication(self):
        a, ai = create_response(self.writer, request_id=self.parent.pk, body_text='Same work text')
        b, bi = create_response(self.writer, request_id=self.parent.pk, body_text='Same work text')
        self.assertNotEqual(a.pk, b.pk)
        self.assertNotEqual(ai.code, bi.code)
        self.assertEqual(Letter.objects.count(), 2)
        self.assertEqual(LetterInstance.objects.count(), 2)

    def test_late_physical_failure_rolls_back_authored_letter(self):
        before = self.counts()
        with patch('letters.domain_writes.LetterInstance.save', side_effect=IntegrityError('simulated physical failure')):
            with self.assertRaises(IntegrityError):
                create_response(self.writer, request_id=self.parent.pk, body_text='Rollback this')
        self.assertEqual(before, self.counts())

    def test_anonymous_pending_suspended_and_inactive_cannot_write(self):
        candidates = [None, AnonymousUser()]
        for index, (status, active) in enumerate((('pending', True), ('rejected', True), ('suspended', True), ('unknown', True), ('approved', False))):
            candidates.append(get_user_model().objects.create_user(username=f'denied-{index}', participant_status=status, is_active=active, is_staff=True, is_superuser=True))
        before = self.counts()
        for user in candidates:
            with self.assertRaises(PermissionDenied):
                create_request(user, recipient_id=self.person.pk, prompt='Denied')
            with self.assertRaises(PermissionDenied):
                create_response(user, request_id=self.parent.pk, body_text='Denied')
        self.assertEqual(before, self.counts())

    def test_stale_approval_and_defaults_are_reread(self):
        get_user_model().objects.filter(pk=self.writer.pk).update(default_request_visibility='participants_only', default_body_visibility='participants_only')
        request = create_request(self.writer, recipient_id=self.person.pk, prompt='Use persisted defaults')
        letter, _ = create_response(self.writer, request_id=self.parent.pk, body_text='Use persisted defaults')
        self.assertEqual(request.requested_visibility, 'participants_only')
        self.assertEqual(letter.requested_visibility, 'participants_only')
        get_user_model().objects.filter(pk=self.writer.pk).update(participant_status='suspended')
        before = self.counts()
        with self.assertRaises(PermissionDenied):
            create_response(self.writer, request_id=self.parent.pk, body_text='Stale approval')
        with self.assertRaises(PermissionDenied):
            create_request(self.writer, recipient_id=self.person.pk, prompt='Stale approval')
        self.assertEqual(before, self.counts())

    def test_closed_unpublished_and_missing_requests_reject_without_side_effects(self):
        before = self.counts()
        for published, opened in ((False, True), (True, False)):
            LetterRequest.objects.filter(pk=self.parent.pk).update(is_published=published, is_open=opened)
            with self.assertRaises(PermissionDenied):
                create_response(self.writer, request_id=self.parent.pk, body_text='Unavailable')
        with self.assertRaises(PermissionDenied):
            create_response(self.writer, request_id=self.parent.pk + 100, body_text='Missing')
        self.assertEqual(before, self.counts())

    def test_invalid_text_audience_and_identifiers_do_not_write(self):
        before = self.counts()
        for text in ('', '   ', None, 12):
            with self.assertRaises(ValidationError):
                create_request(self.writer, recipient_id=self.person.pk, prompt=text)
            with self.assertRaises(ValidationError):
                create_response(self.writer, request_id=self.parent.pk, body_text=text)
        for visibility in ('friends', '', True):
            with self.assertRaises(ValidationError):
                create_request(self.writer, recipient_id=self.person.pk, prompt='Prompt', requested_visibility=visibility)
            with self.assertRaises(ValidationError):
                create_response(self.writer, request_id=self.parent.pk, body_text='Body', requested_visibility=visibility)
        for identifier in (None, True, 0, -1, '1'):
            with self.assertRaises(ValidationError):
                create_request(self.writer, recipient_id=identifier, prompt='Prompt')
            with self.assertRaises(ValidationError):
                create_response(self.writer, request_id=identifier, body_text='Body')
        self.assertEqual(before, self.counts())

    def test_inactive_recipient_or_destination_is_rejected(self):
        before = self.counts()
        self.person.is_active = False
        self.person.save()
        with self.assertRaises(ValidationError):
            create_request(self.writer, recipient_id=self.person.pk, prompt='Unavailable')
        self.person.is_active = True
        self.person.save()
        self.place.is_active = False
        self.place.save()
        with self.assertRaises(ValidationError):
            create_request(self.writer, recipient_id=self.person.pk, prompt='Unavailable')
        self.assertEqual(before, self.counts())

    def test_city_only_destination_and_explicit_audience(self):
        person = Person.objects.create(nickname='City-only alias', city='Only city')
        request = create_request(self.writer, recipient_id=person.pk, prompt='Prompt', requested_visibility='participants_only')
        self.assertIsNone(request.destination_place_id)
        self.assertEqual(request.destination_city, 'Only city')
        self.assertEqual(request.requested_visibility, 'participants_only')
        letter, instance = create_response(self.writer, request_id=self.parent.pk, body_text='Body', requested_visibility='public')
        self.assertEqual(letter.requested_visibility, 'public')
        self.assertFalse(letter.is_published)
        self.assertFalse(instance.is_public)

    def test_client_controlled_authority_fields_are_not_service_parameters(self):
        before = self.counts()
        for field in ('owner_id', 'submitted_by_id', 'is_published', 'automatically_restricted', 'legacy_source_id'):
            with self.assertRaises(TypeError):
                create_request(self.writer, recipient_id=self.person.pk, prompt='Prompt', **{field: self.owner.pk})
        for field in ('writer_id', 'is_public', 'is_published', 'status', 'authored_letter_id'):
            with self.assertRaises(TypeError):
                create_response(self.writer, request_id=self.parent.pk, body_text='Body', **{field: self.owner.pk})
        self.assertEqual(before, self.counts())

    def test_existing_targets_and_legacy_rows_are_not_modified(self):
        concept = LetterConcept.objects.create(created_for=self.person, write_prompt='Legacy prompt')
        old = Letter.objects.create(body_text='Reviewed work')
        instance = LetterInstance.objects.create(concept=concept, recipient=self.person, authored_letter=old, body_text='Legacy body', code='PRESERVE')
        before = {model._meta.label: list(model.objects.order_by('pk').values()) for model in (LetterConcept, LetterRequest, Letter, LetterInstance)}
        create_response(self.writer, request_id=self.parent.pk, body_text='New work')
        for model in (LetterConcept, LetterRequest, Letter, LetterInstance):
            for row in before[model._meta.label]:
                self.assertEqual(model.objects.values().get(pk=row['id']), row)
