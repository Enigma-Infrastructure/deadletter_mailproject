import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from people.models import Person, Place
from .models import Letter, LetterConcept, LetterHop, LetterInstance, LetterRequest, Stamp, StampUpdate
from .source_backfill import BackfillConflict, backfill_sources


class SourceBackfillTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='organizer')
        self.place = Place.objects.create(name='Private destination', city='Original city')
        self.person = Person.objects.create(nickname='Private recipient', pirate_place=self.place)
        self.concept = LetterConcept.objects.create(created_for=self.person, destination_place=self.place, write_prompt='Private prompt', created_by=self.user)
        self.instance = LetterInstance.objects.create(concept=self.concept, recipient=self.person, body_text='Private body', code='KEEP-CODE', is_public=False, created_by=self.user)
        self.stamp = Stamp.objects.create(letter=self.instance, number='KEEPSTAMP')
        StampUpdate.objects.create(stamp=self.stamp, note='Private note')
        LetterHop.objects.create(letter=self.instance, notes='Private journey')

    def snapshot(self):
        return {model._meta.label: list(model.objects.order_by('pk').values()) for model in (LetterConcept, LetterInstance, Stamp, StampUpdate, LetterHop, LetterRequest, Letter)}

    def test_preview_has_no_writes_and_no_private_output(self):
        before = self.snapshot()
        output = io.StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command('backfill_letter_sources', stdout=output)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(all(q['sql'].lstrip().upper().startswith(('SELECT', 'SAVEPOINT', 'RELEASE', 'BEGIN', 'COMMIT')) for q in queries))
        report = json.loads(output.getvalue())
        self.assertEqual(report['mode'], 'preview')
        self.assertEqual(report['requests_to_create'], 1)
        self.assertEqual(report['letters_created'], 0)
        for value in ('Private', 'KEEP-CODE', 'KEEPSTAMP', 'organizer'):
            self.assertNotIn(value, output.getvalue())

    def test_apply_preserves_legacy_history_and_safe_attribution(self):
        before = self.snapshot()
        report = backfill_sources(apply=True)
        self.assertEqual(report['requests_created'], 1)
        self.assertEqual(report['letters_created'], 1)
        after = self.snapshot()
        for key in before:
            if key not in ('letters.LetterInstance', 'letters.LetterRequest', 'letters.Letter'):
                self.assertEqual(before[key], after[key])
        old_instance = dict(before['letters.LetterInstance'][0])
        new_instance = dict(after['letters.LetterInstance'][0])
        new_instance.pop('authored_letter_id')
        old_instance.pop('authored_letter_id')
        self.assertEqual(old_instance, new_instance)
        request = LetterRequest.objects.get()
        letter = Letter.objects.get()
        self.assertEqual(request.legacy_source_id, self.concept.pk)
        self.assertEqual(letter.request_id, request.pk)
        self.assertEqual(letter.body_text, self.instance.body_text)
        self.assertEqual(letter.prompt_snapshot, self.concept.write_prompt)
        self.assertEqual(letter.recipient_alias, self.person.nickname)
        self.assertEqual(letter.destination_label, 'Private destination · Original city')
        self.assertEqual(request.created_at, self.concept.created_at)
        self.assertEqual(letter.created_at, self.instance.created_at)
        self.assertIsNone(request.owner_id)
        self.assertIsNone(request.submitted_by_id)
        self.assertIsNone(letter.writer_id)
        self.assertIsNone(request.concept_id)
        self.assertIsNone(letter.concept_id)
        self.assertIsNone(letter.finalized_at)
        for row in (request, letter):
            self.assertFalse(row.is_published)
            self.assertEqual(row.requested_visibility, 'participants_only')
        self.assertTrue(letter.automatically_restricted)
        self.assertEqual(letter.restriction_reason, 'legacy_hidden')
        self.person.nickname = 'Renamed'
        self.person.save()
        self.place.name = 'Moved'
        self.place.save()
        letter.refresh_from_db()
        self.assertEqual(letter.recipient_alias, 'Private recipient')
        self.assertEqual(letter.destination_label, 'Private destination · Original city')

    def test_repeat_preserves_edited_targets_and_existing_links(self):
        backfill_sources(apply=True)
        LetterRequest.objects.update(prompt='Edited request')
        Letter.objects.update(body_text='Edited work')
        before = self.snapshot()
        report = backfill_sources(apply=True)
        self.assertEqual(report['requests_created'], 0)
        self.assertEqual(report['letters_created'], 0)
        self.assertEqual(before, self.snapshot())

    def test_multiple_instances_are_not_deduplicated_and_unanswered_request_survives(self):
        LetterInstance.objects.create(concept=self.concept, recipient=self.person, body_text=self.instance.body_text)
        LetterConcept.objects.create(created_for=self.person, write_prompt='Unanswered')
        backfill_sources(apply=True)
        self.assertEqual(LetterRequest.objects.count(), 2)
        self.assertEqual(Letter.objects.count(), 2)
        self.assertEqual(Letter.objects.values('request_id').distinct().count(), 1)

    def test_conflict_or_missing_recipient_aborts_before_any_writes(self):
        other = Person.objects.create(nickname='Other recipient')
        for recipient in (other, None):
            LetterInstance.objects.filter(pk=self.instance.pk).update(recipient=recipient)
            before = self.snapshot()
            for apply in (False, True):
                with self.assertRaises(BackfillConflict):
                    backfill_sources(apply=apply)
                self.assertEqual(before, self.snapshot())

    def test_unowned_concept_and_orphan_instance_get_no_inferred_request(self):
        concept = LetterConcept.objects.create(write_prompt='Reusable or incomplete')
        a = LetterInstance.objects.create(concept=concept, recipient=self.person)
        b = LetterInstance.objects.create(recipient=self.person)
        backfill_sources(apply=True)
        self.assertEqual(LetterRequest.objects.count(), 1)
        for instance in (a, b):
            instance.refresh_from_db()
            self.assertIsNone(instance.authored_letter.request_id)
            self.assertIsNone(instance.authored_letter.concept_id)
        self.assertEqual(b.authored_letter.destination_place_id, self.place.pk)

    def test_existing_mapping_is_reused_without_overwrite(self):
        request = LetterRequest.objects.create(legacy_source=self.concept, prompt='Reviewed prompt', owner=self.user)
        backfill_sources(apply=True)
        request.refresh_from_db()
        self.assertEqual(request.prompt, 'Reviewed prompt')
        self.assertEqual(request.owner_id, self.user.pk)
        self.assertEqual(Letter.objects.get().request_id, request.pk)

    def test_public_legacy_flag_does_not_publish_new_records(self):
        LetterInstance.objects.update(is_public=True)
        backfill_sources(apply=True)
        letter = Letter.objects.get()
        self.assertFalse(letter.is_published)
        self.assertFalse(letter.automatically_restricted)
        self.assertEqual(letter.requested_visibility, 'participants_only')

    def test_late_failure_rolls_back_every_write(self):
        before = self.snapshot()
        with patch('letters.source_backfill.snapshots', side_effect=[{}, OperationalError('private database detail')]):
            with self.assertRaises(OperationalError):
                backfill_sources(apply=True)
        self.assertEqual(before, self.snapshot())

    def test_command_error_does_not_leak_database_details(self):
        output = io.StringIO()
        with patch('letters.management.commands.backfill_letter_sources.backfill_sources', side_effect=OperationalError('PRIVATE-SQL')):
            with self.assertRaises(CommandError) as error:
                call_command('backfill_letter_sources', apply=True, stdout=output)
        self.assertNotIn('PRIVATE-SQL', str(error.exception))
        self.assertEqual(output.getvalue(), '')

    def test_empty_database(self):
        StampUpdate.objects.all().delete()
        LetterHop.objects.all().delete()
        Stamp.objects.all().delete()
        LetterInstance.objects.all().delete()
        LetterConcept.objects.all().delete()
        for apply in (False, True):
            report = backfill_sources(apply=apply)
            self.assertEqual(report['requests_to_create'], 0)
            self.assertEqual(report['letters_to_create'], 0)
