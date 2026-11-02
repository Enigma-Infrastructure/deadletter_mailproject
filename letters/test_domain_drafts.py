from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import ReputationEvent
from media_app.models import MediaItem
from people.models import Person
from .domain_access import can_read_saved_letter
from .domain_drafts import authored_letter_drafts, edit_letter_draft, edit_request_draft, owned_request_drafts
from .domain_writes import create_request, create_response
from .models import Letter, LetterConcept, LetterHop, LetterInstance, LetterRequest, Stamp


class DomainDraftTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner', participant_status='approved')
        self.writer = User.objects.create_user(username='writer', participant_status='approved')
        self.person = Person.objects.create(nickname='Saved alias')
        self.request = create_request(self.owner, recipient_id=self.person.pk, prompt='Original prompt')
        self.parent = LetterRequest.objects.create(owner=self.owner, recipient=self.person, prompt='Published prompt', recipient_alias='Saved alias', is_published=True)
        self.letter, self.instance = create_response(self.writer, request_id=self.parent.pk, body_text='Original body')

    def snapshot(self):
        return {model._meta.label: list(model.objects.order_by('pk').values()) for model in (LetterRequest, Letter, LetterInstance, Stamp, LetterHop, MediaItem, ReputationEvent)}

    def test_workspace_is_owned_and_distinct_from_audience_reads(self):
        self.assertEqual(list(owned_request_drafts(self.owner).values_list('pk', flat=True)), [self.request.pk])
        self.assertFalse(owned_request_drafts(self.writer).exists())
        self.assertEqual(list(authored_letter_drafts(self.writer).values_list('pk', flat=True)), [self.letter.pk])
        self.assertFalse(authored_letter_drafts(self.owner).exists())
        self.assertFalse(can_read_saved_letter(self.writer, self.letter.pk))
        self.assertFalse(owned_request_drafts(AnonymousUser()).exists())
        self.assertFalse(authored_letter_drafts(None).exists())

    def test_request_edit_preserves_identity_snapshots_and_review(self):
        before = LetterRequest.objects.values().get(pk=self.request.pk)
        row = edit_request_draft(self.owner, request_id=self.request.pk, prompt='  New prompt  ', requested_visibility='participants_only')
        after = LetterRequest.objects.values().get(pk=row.pk)
        for key in before:
            if key not in ('prompt', 'requested_visibility'):
                self.assertEqual(before[key], after[key])
        self.assertEqual(row.prompt, '  New prompt  ')
        self.assertEqual(row.requested_visibility, 'participants_only')

    def test_letter_edit_atomically_mirrors_body_only(self):
        before = self.snapshot()
        letter, instance = edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='  New body\n', requested_visibility='participants_only')
        after = self.snapshot()
        for label, rows in before.items():
            for index, row in enumerate(rows):
                for key, value in row.items():
                    mutable = (label == 'letters.Letter' and key in ('body_text', 'requested_visibility')) or (label == 'letters.LetterInstance' and key == 'body_text')
                    if not mutable:
                        self.assertEqual(after[label][index][key], value)
        self.assertEqual(letter.body_text, '  New body\n')
        self.assertEqual(instance.body_text, letter.body_text)
        self.assertFalse(instance.is_public)
        self.assertFalse(letter.is_published)
        self.assertTrue(letter.automatically_restricted)

    def test_default_audience_is_preserved_not_reset_to_account_preference(self):
        Letter.objects.filter(pk=self.letter.pk).update(requested_visibility='participants_only')
        letter, _ = edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='New body')
        self.assertEqual(letter.requested_visibility, 'participants_only')

    def test_wrong_owner_writer_staff_and_submitter_do_not_bypass(self):
        get_user_model().objects.filter(pk=self.owner.pk).update(is_staff=True, is_superuser=True)
        LetterRequest.objects.filter(pk=self.request.pk).update(submitted_by=self.writer)
        before = self.snapshot()
        with self.assertRaises(PermissionDenied):
            edit_request_draft(self.writer, request_id=self.request.pk, prompt='Wrong owner')
        with self.assertRaises(PermissionDenied):
            edit_letter_draft(self.owner, letter_id=self.letter.pk, body_text='Wrong writer')
        self.assertEqual(before, self.snapshot())

    def test_revocation_denies_read_and_edit_despite_stale_user(self):
        for status, active in (('pending', True), ('rejected', True), ('suspended', True), ('approved', False)):
            get_user_model().objects.filter(pk=self.writer.pk).update(participant_status=status, is_active=active)
            self.assertFalse(authored_letter_drafts(self.writer).exists())
            with self.assertRaises(PermissionDenied):
                edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Denied')
        before = self.snapshot()
        with self.assertRaises(PermissionDenied):
            edit_request_draft(None, request_id=self.request.pk, prompt='Denied')
        self.assertEqual(before, self.snapshot())

    def test_request_with_responses_or_historical_mapping_cannot_be_edited(self):
        Letter.objects.create(request=self.request)
        with self.assertRaises(PermissionDenied):
            edit_request_draft(self.owner, request_id=self.request.pk, prompt='Cannot change snapshots')
        Letter.objects.filter(request=self.request).delete()
        concept = LetterConcept.objects.create()
        LetterRequest.objects.filter(pk=self.request.pk).update(legacy_source=concept)
        with self.assertRaises(PermissionDenied):
            edit_request_draft(self.owner, request_id=self.request.pk, prompt='Cannot rewrite historical source')

    def test_published_finalized_or_other_restriction_reason_is_not_editable(self):
        for changes in ({'is_published': True}, {'finalized_at': timezone.now()}, {'restriction_reason': 'legacy_hidden'}, {'automatically_restricted': False}):
            Letter.objects.filter(pk=self.letter.pk).update(is_published=False, finalized_at=None, restriction_reason='review_required', automatically_restricted=True)
            Letter.objects.filter(pk=self.letter.pk).update(**changes)
            with self.assertRaises(PermissionDenied):
                edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Denied')
        LetterRequest.objects.filter(pk=self.request.pk).update(is_published=True)
        with self.assertRaises(PermissionDenied):
            edit_request_draft(self.owner, request_id=self.request.pk, prompt='Denied')

    def test_physical_production_and_body_disagreement_block_edits(self):
        baseline = LetterInstance.objects.values().get(pk=self.instance.pk)
        for changes in ({'is_public': True}, {'printed_at': timezone.now()}, {'needs_printing': False}, {'status': 'waiting_print'}, {'origin': 'desk'}, {'body_text': 'Divergent body'}):
            LetterInstance.objects.filter(pk=self.instance.pk).update(**{key: value for key, value in baseline.items() if key != 'id'})
            LetterInstance.objects.filter(pk=self.instance.pk).update(**changes)
            before = self.snapshot()
            with self.assertRaises(PermissionDenied):
                edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Denied')
            self.assertEqual(before, self.snapshot())

    def test_multiple_or_missing_instances_block_edits(self):
        extra = LetterInstance.objects.create(authored_letter=self.letter)
        with self.assertRaises(PermissionDenied):
            edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Denied')
        extra.delete()
        self.instance.delete()
        with self.assertRaises(PermissionDenied):
            edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Denied')

    def test_any_physical_history_blocks_edits(self):
        for model, fields in ((Stamp, {'number': 'DRAFTSTAMP'}), (LetterHop, {'notes': 'History'}), (MediaItem, {'file': 'private/draft.png'}), (ReputationEvent, {'user': self.writer, 'reason': 'note'})):
            record = model.objects.create(letter=self.instance, **fields)
            before = self.snapshot()
            with self.assertRaises(PermissionDenied):
                edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Denied')
            self.assertEqual(before, self.snapshot())
            record.delete()

    def test_second_write_failure_rolls_back_letter_edit(self):
        before = self.snapshot()
        with patch('letters.domain_drafts.LetterInstance.save', side_effect=IntegrityError('simulated mirror failure')):
            with self.assertRaises(IntegrityError):
                edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Rollback')
        self.assertEqual(before, self.snapshot())

    def test_invalid_input_and_missing_records_have_no_side_effects(self):
        before = self.snapshot()
        for text in ('', '   ', None):
            with self.assertRaises(ValidationError):
                edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text=text)
            with self.assertRaises(ValidationError):
                edit_request_draft(self.owner, request_id=self.request.pk, prompt=text)
        with self.assertRaises(ValidationError):
            edit_letter_draft(self.writer, letter_id=self.letter.pk, body_text='Body', requested_visibility='friends')
        with self.assertRaises(PermissionDenied):
            edit_letter_draft(self.writer, letter_id=self.letter.pk + 100, body_text='Missing')
        with self.assertRaises(TypeError):
            edit_request_draft(self.owner, request_id=self.request.pk, prompt='Prompt', is_published=True)
        self.assertEqual(before, self.snapshot())

    def test_workspace_queries_are_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            list(owned_request_drafts(self.owner))
            list(authored_letter_drafts(self.writer))
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in queries))
