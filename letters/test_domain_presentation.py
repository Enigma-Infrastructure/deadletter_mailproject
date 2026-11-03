import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from people.models import Person, Place
from .domain_presentation import (letter_card, letter_cards, letter_draft_card, request_card, request_cards, request_draft_card)
from .models import Letter, LetterInstance, LetterRequest, Stamp


class DomainPresentationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='ACCOUNT-SENTINEL', email='private-sentinel@example.org', participant_status='approved')
        self.other = User.objects.create_user(username='other', participant_status='approved')
        place = Place.objects.create(name='LOCATION-SENTINEL', city='CITY-SENTINEL')
        person = Person.objects.create(nickname='Live profile alias', email='recipient-sentinel@example.org', pirate_place=place)
        self.request = LetterRequest.objects.create(owner=self.user, submitted_by=self.user, recipient=person, recipient_alias='Permitted alias', prompt='Permitted prompt', destination_place=place, destination_city='CITY-SENTINEL', destination_label='ADDRESS-SENTINEL', is_published=True, requested_visibility='public', restriction_reason='REASON-SENTINEL')
        self.letter = Letter.objects.create(request=self.request, writer=self.user, body_text='Permitted body', recipient=person, recipient_alias='Permitted alias', prompt_snapshot='SNAPSHOT-SENTINEL', destination_place=place, destination_city='CITY-SENTINEL', destination_label='ADDRESS-SENTINEL', is_published=True, requested_visibility='public', restriction_reason='REASON-SENTINEL')
        instance = LetterInstance.objects.create(authored_letter=self.letter, code='TRACKING-SENTINEL')
        Stamp.objects.create(letter=instance, number='STAMP-SENTINEL')

    def test_exact_allowlists_and_no_related_metadata(self):
        expected_request = {'id': self.request.pk, 'prompt': 'Permitted prompt', 'recipient_alias': 'Permitted alias'}
        expected_letter = {'id': self.letter.pk, 'body_text': 'Permitted body', 'recipient_alias': 'Permitted alias'}
        for user in (None, AnonymousUser(), self.user):
            self.assertEqual(request_card(user, self.request.pk), expected_request)
            self.assertEqual(letter_card(user, self.letter.pk), expected_letter)
            self.assertEqual(request_cards(user), [expected_request])
            self.assertEqual(letter_cards(user), [expected_letter])
        text = json.dumps([expected_request, letter_card(self.user, self.letter.pk)])
        for marker in ('ACCOUNT-SENTINEL', 'LOCATION-SENTINEL', 'CITY-SENTINEL', 'ADDRESS-SENTINEL', 'REASON-SENTINEL', 'TRACKING-SENTINEL', 'STAMP-SENTINEL', 'SNAPSHOT-SENTINEL', 'private-sentinel@example.org', 'recipient-sentinel@example.org', 'Live profile alias'):
            self.assertNotIn(marker, text)

    def test_parent_audience_limits_bodies_and_lists(self):
        LetterRequest.objects.filter(pk=self.request.pk).update(requested_visibility='participants_only')
        self.assertIsNone(request_card(None, self.request.pk))
        self.assertIsNone(letter_card(None, self.letter.pk))
        self.assertEqual(request_cards(None), [])
        self.assertEqual(letter_cards(None), [])
        self.assertIsNotNone(letter_card(self.user, self.letter.pk))
        LetterRequest.objects.filter(pk=self.request.pk).update(is_published=False)
        self.assertIsNone(letter_card(self.user, self.letter.pk))
        self.assertEqual(letter_cards(self.user), [])

    def test_restricted_body_does_not_hide_public_prompt(self):
        Letter.objects.filter(pk=self.letter.pk).update(automatically_restricted=True)
        self.assertIsNotNone(request_card(None, self.request.pk))
        self.assertIsNone(letter_card(None, self.letter.pk))
        self.assertEqual(letter_cards(None), [])
        self.assertIsNotNone(letter_card(self.user, self.letter.pk))

    def test_workspace_does_not_broaden_audience_or_parent_access(self):
        Letter.objects.filter(pk=self.letter.pk).update(is_published=False)
        LetterRequest.objects.filter(pk=self.request.pk).update(is_published=False, owner=self.other, submitted_by=self.user)
        self.assertIsNone(letter_card(self.user, self.letter.pk))
        self.assertIsNone(request_draft_card(self.user, self.request.pk))
        self.assertIsNotNone(request_draft_card(self.other, self.request.pk))
        self.assertEqual(set(letter_draft_card(self.user, self.letter.pk)), {'id', 'body_text', 'recipient_alias'})
        self.assertIsNone(letter_draft_card(self.other, self.letter.pk))
        self.assertIsNone(letter_draft_card(None, self.letter.pk))
        self.assertIsNone(request_draft_card(None, self.request.pk))

    def test_approval_changes_are_not_cached(self):
        LetterRequest.objects.update(requested_visibility='participants_only')
        self.assertIsNotNone(letter_card(self.user, self.letter.pk))
        get_user_model().objects.filter(pk=self.user.pk).update(participant_status='suspended')
        self.assertIsNone(letter_card(self.user, self.letter.pk))
        self.assertEqual(letter_cards(self.user), [])
        Letter.objects.update(is_published=False)
        self.assertIsNone(letter_draft_card(self.user, self.letter.pk))

    def test_missing_invalid_and_inaccessible_ids_return_same_shape(self):
        for identifier in (None, True, 0, -1, '1', self.letter.pk + self.request.pk + 100):
            self.assertIsNone(request_card(None, identifier))
            self.assertIsNone(letter_card(None, identifier))
            self.assertIsNone(request_draft_card(self.user, identifier))
            self.assertIsNone(letter_draft_card(self.user, identifier))

    def test_bounded_lists_have_deterministic_order_and_only_authorized_rows(self):
        first = Letter.objects.create(body_text='First standalone', is_published=True, requested_visibility='public')
        second = Letter.objects.create(body_text='Second standalone', is_published=True, requested_visibility='public')
        Letter.objects.filter(pk=second.pk).update(created_at=first.created_at)
        Letter.objects.create(body_text='HIDDEN-SENTINEL')
        self.assertEqual([row['id'] for row in letter_cards(None, limit=2)], [second.pk, first.pk])
        self.assertNotIn('HIDDEN-SENTINEL', json.dumps(letter_cards(None)))
        for limit in (None, True, 0, -1, 101, '20'):
            with self.assertRaises(ValidationError):
                letter_cards(None, limit=limit)
            with self.assertRaises(ValidationError):
                request_cards(None, limit=limit)

    def test_readonly_and_results_do_not_mutate_models(self):
        with CaptureQueriesContext(connection) as queries:
            card = letter_card(self.user, self.letter.pk)
            request_cards(self.user)
            letter_cards(self.user)
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries))
        card['body_text'] = 'Caller mutation'
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.body_text, 'Permitted body')

    def test_text_is_not_html_sanitized_or_claimed_pii_free(self):
        value = '<script>untrusted()</script> Contact private@example.org'
        Letter.objects.filter(pk=self.letter.pk).update(body_text=value)
        self.assertEqual(letter_card(None, self.letter.pk)['body_text'], value)
