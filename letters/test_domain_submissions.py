from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from people.models import Person
from .domain_drafts import edit_letter_draft
from .domain_submissions import SubmissionConflict, submit_request, submit_response
from .models import DomainSubmissionReceipt, Letter, LetterInstance, LetterRequest


class SubmissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='submitter', participant_status='approved')
        self.other = User.objects.create_user(username='other', participant_status='approved')
        self.person = Person.objects.create(nickname='Private alias')
        self.parent = LetterRequest.objects.create(recipient=self.person, is_published=True)
        self.key = str(uuid4())

    def request(self, **overrides):
        data = {'submission_key': self.key, 'recipient_id': self.person.pk, 'prompt': 'Private prompt'}
        data.update(overrides)
        return submit_request(self.user, **data)

    def response(self, **overrides):
        data = {'submission_key': self.key, 'request_id': self.parent.pk, 'body_text': 'Private body'}
        data.update(overrides)
        return submit_response(self.user, **data)

    def test_request_and_response_replay_original_ids(self):
        request, replay = self.request()
        self.assertFalse(replay)
        again, replay = self.request(submission_key=self.key.upper())
        self.assertTrue(replay)
        self.assertEqual(request.pk, again.pk)
        letter, instance, replay = self.response()
        self.assertFalse(replay)
        again, copy, replay = self.response()
        self.assertTrue(replay)
        self.assertEqual((letter.pk, instance.pk, instance.code), (again.pk, copy.pk, copy.code))
        self.assertEqual(DomainSubmissionReceipt.objects.count(), 2)
        self.assertEqual(Letter.objects.count(), 1)
        self.assertEqual(LetterInstance.objects.count(), 1)

    def test_payload_mismatch_never_creates_or_overwrites(self):
        self.request()
        self.response()
        for changes in ({'prompt': 'Changed'}, {'requested_visibility': 'public'}):
            with self.assertRaises(SubmissionConflict):
                self.request(**changes)
        for changes in ({'body_text': 'Changed'}, {'requested_visibility': 'participants_only'}, {'request_id': self.parent.pk + 100}):
            with self.assertRaises(SubmissionConflict):
                self.response(**changes)
        self.assertEqual(Letter.objects.get().body_text, 'Private body')
        self.assertEqual(DomainSubmissionReceipt.objects.count(), 2)

    def test_distinct_keys_and_actors_do_not_deduplicate_text(self):
        self.request()
        self.request(submission_key=str(uuid4()))
        submit_request(self.other, submission_key=self.key, recipient_id=self.person.pk, prompt='Private prompt')
        self.assertEqual(DomainSubmissionReceipt.objects.count(), 3)
        self.assertEqual(LetterRequest.objects.count(), 4)

    def test_replay_does_not_reset_edits_or_current_defaults(self):
        request, _ = self.request()
        get_user_model().objects.filter(pk=self.user.pk).update(default_request_visibility='participants_only')
        LetterRequest.objects.filter(pk=request.pk).update(prompt='Reviewed edit')
        again, replay = self.request()
        self.assertTrue(replay)
        self.assertEqual(again.prompt, 'Reviewed edit')
        self.assertEqual(again.requested_visibility, 'public')
        letter, _, _ = self.response()
        edit_letter_draft(self.user, letter_id=letter.pk, body_text='Edited body')
        LetterRequest.objects.filter(pk=self.parent.pk).update(is_published=False, is_open=False)
        again, _, replay = self.response()
        self.assertTrue(replay)
        self.assertEqual(again.body_text, 'Edited body')

    def test_revoked_actor_cannot_replay(self):
        self.response()
        get_user_model().objects.filter(pk=self.user.pk).update(participant_status='suspended')
        with self.assertRaises(PermissionDenied):
            self.response()
        self.assertEqual(DomainSubmissionReceipt.objects.count(), 1)

    def test_missing_result_is_tombstoned_not_recreated(self):
        request, _ = self.request()
        request.delete()
        with self.assertRaises(SubmissionConflict):
            self.request()
        letter, instance, _ = self.response()
        instance.delete()
        with self.assertRaises(SubmissionConflict):
            self.response()
        self.assertEqual(Letter.objects.count(), 1)
        self.assertEqual(LetterInstance.objects.count(), 0)

    def test_receipt_and_all_results_roll_back_on_failure(self):
        with patch('letters.domain_submissions.create_response', side_effect=IntegrityError('Simulated failure')):
            with self.assertRaises(IntegrityError):
                self.response()
        self.assertFalse(DomainSubmissionReceipt.objects.exists())
        with patch('letters.domain_submissions.DomainSubmissionReceipt.save', side_effect=IntegrityError('Receipt failure')):
            with self.assertRaises(IntegrityError):
                self.response()
        self.assertFalse(Letter.objects.exists())
        self.assertFalse(LetterInstance.objects.exists())
        self.assertFalse(DomainSubmissionReceipt.objects.exists())
        self.assertFalse(self.response()[2])

    def test_invalid_inputs_and_unavailable_parent_leave_no_receipt(self):
        for key in ('', 'not-a-key', None, 12, '00000000-0000-0000-0000-000000000000'):
            with self.assertRaises(ValidationError):
                self.request(submission_key=key)
        for changes in ({'prompt': ''}, {'recipient_id': True}, {'requested_visibility': 'friends'}):
            with self.assertRaises(ValidationError):
                self.request(**changes)
        LetterRequest.objects.filter(pk=self.parent.pk).update(is_open=False)
        with self.assertRaises(PermissionDenied):
            self.response()
        self.assertFalse(DomainSubmissionReceipt.objects.exists())

    def test_receipts_store_no_raw_keys_prompts_or_bodies(self):
        self.request()
        self.response()
        values = repr(list(DomainSubmissionReceipt.objects.values()))
        for value in (self.key, 'Private prompt', 'Private body', 'Private alias'):
            self.assertNotIn(value, values)

    def test_database_uniqueness_and_known_operation(self):
        self.request()
        receipt = DomainSubmissionReceipt.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            DomainSubmissionReceipt.objects.create(actor=self.user, operation='request', key_digest=receipt.key_digest, payload_digest='x' * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DomainSubmissionReceipt.objects.create(actor=self.user, operation='unknown', key_digest='y' * 64, payload_digest='x' * 64)


class SubmissionConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_simultaneous_identical_submissions_create_one_pair(self):
        user = get_user_model().objects.create_user(username='parallel', participant_status='approved')
        parent = LetterRequest.objects.create(is_published=True)
        key = str(uuid4())
        barrier = Barrier(2)
        def worker():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                letter, instance, replay = submit_response(actor, submission_key=key, request_id=parent.pk, body_text='Concurrent body')
                return letter.pk, instance.pk, replay
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(results[0][:2], results[1][:2])
        self.assertEqual(sorted(row[2] for row in results), [False, True])
        self.assertEqual(Letter.objects.count(), 1)
        self.assertEqual(LetterInstance.objects.count(), 1)
        self.assertEqual(DomainSubmissionReceipt.objects.count(), 1)


class SubmissionMigrationTests(TransactionTestCase):
    def test_schema_upgrade_preserves_existing_content(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [('letters', '0010_request_letter_foundation')]
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            request = apps.get_model('letters', 'LetterRequest').objects.create(prompt='Preserve')
            letter = apps.get_model('letters', 'Letter').objects.create(request_id=request.pk, body_text='Preserve body')
            instance = apps.get_model('letters', 'LetterInstance').objects.create(authored_letter_id=letter.pk, code='KEEP-REPLAY', is_public=False)
            executor = MigrationExecutor(connection)
            target = [('letters', '0011_domain_submission_receipt')]
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            self.assertEqual(apps.get_model('letters', 'DomainSubmissionReceipt').objects.count(), 0)
            self.assertEqual(apps.get_model('letters', 'LetterRequest').objects.get(pk=request.pk).prompt, 'Preserve')
            self.assertEqual(apps.get_model('letters', 'Letter').objects.get(pk=letter.pk).body_text, 'Preserve body')
            self.assertEqual(apps.get_model('letters', 'LetterInstance').objects.get(pk=instance.pk).code, 'KEEP-REPLAY')
        finally:
            MigrationExecutor(connection).migrate(latest)
