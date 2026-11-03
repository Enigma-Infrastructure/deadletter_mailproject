import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from people.models import Person
from .domain_editing import (DraftConflict, TOKEN_MAX_AGE, TOKEN_SALT, letter_draft_snapshot, request_draft_snapshot, save_letter_draft, save_request_draft)
from .domain_writes import create_request, create_response
from .models import Letter, LetterInstance, LetterRequest, Stamp


class DomainEditingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner', participant_status='approved')
        self.writer = User.objects.create_user(username='writer', participant_status='approved')
        person = Person.objects.create(nickname='Alias')
        self.request = create_request(self.owner, recipient_id=person.pk, prompt='Original prompt')
        self.parent = LetterRequest.objects.create(is_published=True, prompt='Parent prompt', recipient_alias='Alias')
        self.letter, self.instance = create_response(self.writer, request_id=self.parent.pk, body_text='Original body')

    def test_request_two_tabs_reject_stale_save(self):
        first = request_draft_snapshot(self.owner, self.request.pk)
        second = request_draft_snapshot(self.owner, self.request.pk)
        saved = save_request_draft(self.owner, request_id=self.request.pk, expected_token=first['edit_token'], prompt='First edit')
        self.assertEqual(saved['card']['prompt'], 'First edit')
        with self.assertRaises(DraftConflict):
            save_request_draft(self.owner, request_id=self.request.pk, expected_token=second['edit_token'], prompt='Lost update')
        self.request.refresh_from_db()
        self.assertEqual(self.request.prompt, 'First edit')
        result = save_request_draft(self.owner, request_id=self.request.pk, expected_token=saved['edit_token'], prompt='Next edit')
        self.assertEqual(result['card']['prompt'], 'Next edit')

    def test_letter_two_tabs_preserve_first_body_and_mirror(self):
        token = letter_draft_snapshot(self.writer, self.letter.pk)['edit_token']
        saved = save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='First edit')
        self.assertEqual(saved['card']['body_text'], 'First edit')
        with self.assertRaises(DraftConflict):
            save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='Stale edit')
        self.letter.refresh_from_db()
        self.instance.refresh_from_db()
        self.assertEqual(self.letter.body_text, 'First edit')
        self.assertEqual(self.instance.body_text, 'First edit')
        self.assertFalse(self.instance.is_public)

    def test_tampered_missing_expired_and_wrong_scope_tokens(self):
        token = request_draft_snapshot(self.owner, self.request.pk)['edit_token']
        for invalid in (None, '', token + 'tampered', 'x' * 4097):
            with self.assertRaises(DraftConflict):
                save_request_draft(self.owner, request_id=self.request.pk, expected_token=invalid, prompt='Denied')
        with self.assertRaises(TypeError):
            save_request_draft(self.owner, request_id=self.request.pk, prompt='Missing token')
        future = time.time() + TOKEN_MAX_AGE + 5
        with patch('django.core.signing.time.time', return_value=future):
            with self.assertRaises(DraftConflict):
                save_request_draft(self.owner, request_id=self.request.pk, expected_token=token, prompt='Expired')
        original = signing.loads(token, salt=TOKEN_SALT)
        for key, value in (('kind', 'letter'), ('id', self.request.pk + 100), ('actor', self.writer.pk), ('database', 'other'), ('v', 99)):
            payload = dict(original, **{key: value})
            wrong = signing.dumps(payload, salt=TOKEN_SALT)
            with self.assertRaises(DraftConflict):
                save_request_draft(self.owner, request_id=self.request.pk, expected_token=wrong, prompt='Wrong scope')
        self.request.refresh_from_db()
        self.assertEqual(self.request.prompt, 'Original prompt')

    def test_approval_and_ownership_are_rechecked_not_granted_by_token(self):
        token = letter_draft_snapshot(self.writer, self.letter.pk)['edit_token']
        with self.assertRaises(PermissionDenied):
            save_letter_draft(self.owner, letter_id=self.letter.pk, expected_token=token, body_text='Not writer')
        get_user_model().objects.filter(pk=self.writer.pk).update(participant_status='suspended')
        with self.assertRaises(PermissionDenied):
            letter_draft_snapshot(self.writer, self.letter.pk)
        with self.assertRaises(PermissionDenied):
            save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='Revoked')
        with self.assertRaises(PermissionDenied):
            request_draft_snapshot(None, self.request.pk)

    def test_snapshot_and_instance_changes_invalidate_token(self):
        for model, pk, changes in ((Letter, self.letter.pk, {'recipient_alias': 'Changed snapshot'}), (LetterInstance, self.instance.pk, {'current_city': 'Changed physical state'})):
            token = letter_draft_snapshot(self.writer, self.letter.pk)['edit_token']
            model.objects.filter(pk=pk).update(**changes)
            with self.assertRaises(DraftConflict):
                save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='Denied')

    def test_lifecycle_guards_still_block_with_fresh_token(self):
        Stamp.objects.create(letter=self.instance)
        token = letter_draft_snapshot(self.writer, self.letter.pk)['edit_token']
        with self.assertRaises(PermissionDenied):
            save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='Has history')
        Letter.objects.create(request=self.request)
        token = request_draft_snapshot(self.owner, self.request.pk)['edit_token']
        with self.assertRaises(PermissionDenied):
            save_request_draft(self.owner, request_id=self.request.pk, expected_token=token, prompt='Has responses')

    def test_failed_mirror_rolls_back_and_original_token_remains_valid(self):
        token = letter_draft_snapshot(self.writer, self.letter.pk)['edit_token']
        with patch('letters.domain_drafts.LetterInstance.save', side_effect=IntegrityError('Mirror failure')):
            with self.assertRaises(IntegrityError):
                save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='Rollback')
        self.letter.refresh_from_db()
        self.instance.refresh_from_db()
        self.assertEqual(self.letter.body_text, 'Original body')
        self.assertEqual(self.instance.body_text, 'Original body')
        saved = save_letter_draft(self.writer, letter_id=self.letter.pk, expected_token=token, body_text='Successful retry')
        self.assertEqual(saved['card']['body_text'], 'Successful retry')

    def test_snapshot_is_allowlisted_and_contains_no_raw_state_in_token(self):
        with CaptureQueriesContext(connection) as queries:
            snapshot = letter_draft_snapshot(self.writer, self.letter.pk)
        self.assertTrue(all(query['sql'].lstrip().upper().startswith(('SELECT', 'SAVEPOINT', 'RELEASE', 'BEGIN', 'COMMIT')) for query in queries))
        self.assertEqual(set(snapshot), {'card', 'edit_token'})
        self.assertEqual(set(snapshot['card']), {'id', 'body_text', 'recipient_alias'})
        payload = signing.loads(snapshot['edit_token'], salt=TOKEN_SALT)
        self.assertEqual(set(payload), {'v', 'kind', 'id', 'actor', 'database', 'digest'})
        self.assertNotIn('Original body', repr(payload))
        self.assertNotIn(self.instance.code, repr(payload))

    def test_exact_state_restoration_is_not_monotonic_revision_history(self):
        token = request_draft_snapshot(self.owner, self.request.pk)['edit_token']
        LetterRequest.objects.filter(pk=self.request.pk).update(prompt='Intermediate change')
        LetterRequest.objects.filter(pk=self.request.pk).update(prompt='Original prompt')
        saved = save_request_draft(self.owner, request_id=self.request.pk, expected_token=token, prompt='Allowed identical-state edit')
        self.assertEqual(saved['card']['prompt'], 'Allowed identical-state edit')
