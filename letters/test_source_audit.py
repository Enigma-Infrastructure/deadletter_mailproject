import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import ReputationEvent
from media_app.models import MediaItem
from people.models import Person, Place
from .models import Letter, LetterConcept, LetterHop, LetterInstance, LetterRequest, Stamp, StampUpdate
from .source_audit import collect_audit


class SourceAuditTests(TestCase):
    def setUp(self):
        self.secret = 'AUDIT-PRIVATE-SENTINEL'
        self.user = get_user_model().objects.create_user(username=self.secret, email='private-sentinel@example.org')
        place = Place.objects.create(name=self.secret, city=self.secret)
        a = Person.objects.create(nickname=self.secret, pirate_place=place, email='recipient-sentinel@example.org')
        b = Person.objects.create(nickname='Other private alias', pirate_place=place)
        LetterConcept.objects.create(title=self.secret)
        shared = LetterConcept.objects.create(title=self.secret, write_prompt=self.secret, created_for=a, destination_place=place)
        one = LetterConcept.objects.create(title=self.secret, created_for=a)
        first = LetterInstance.objects.create(concept=shared, recipient=a, body_text=self.secret, printed_at=timezone.now(), needs_printing=False)
        LetterInstance.objects.create(concept=shared, recipient=b, is_public=False)
        LetterInstance.objects.create(concept=one)
        LetterInstance.objects.create(recipient=b)
        request = LetterRequest.objects.create(legacy_source=shared, owner=self.user, prompt=self.secret)
        letter = Letter.objects.create(request=request, writer=self.user, body_text='Different private body')
        first.authored_letter = letter
        first.save(update_fields=['authored_letter'])
        stamp = Stamp.objects.create(letter=first)
        Stamp.objects.create(letter=first)
        StampUpdate.objects.create(stamp=stamp, note=self.secret)
        LetterHop.objects.create(letter=first, notes=self.secret)
        MediaItem.objects.create(letter=first, file='letters/private-sentinel.png', caption=self.secret)
        ReputationEvent.objects.create(user=self.user, letter=first, reason='spotted', reputation=5)

    def test_counts_and_join_cardinality(self):
        report = collect_audit()
        self.assertEqual(report['schema_version'], 1)
        concepts = report['legacy_concepts']
        self.assertEqual(concepts['total'], 3)
        self.assertEqual(concepts['with_recipient'], 2)
        self.assertEqual(concepts['without_recipient'], 1)
        self.assertEqual(concepts['with_no_instances'], 1)
        self.assertEqual(concepts['with_one_instance'], 1)
        self.assertEqual(concepts['with_multiple_instances'], 1)
        self.assertEqual(concepts['with_multiple_instance_recipients'], 1)
        self.assertEqual(concepts['already_mapped_to_request'], 1)
        instances = report['physical_instances']
        self.assertEqual(instances['total'], 4)
        self.assertEqual(instances['without_concept'], 1)
        self.assertEqual(instances['without_recipient'], 1)
        self.assertEqual(instances['recipient_disagrees_with_concept'], 1)
        self.assertEqual(instances['with_authored_letter'], 1)
        self.assertEqual(instances['linked_legacy_body_differs_from_authored_body'], 1)
        self.assertEqual(instances['legacy_public_flag_false'], 1)
        self.assertEqual(instances['with_printed_timestamp'], 1)
        history = report['physical_history']
        self.assertEqual(history['stamps'], 2)
        self.assertEqual(history['instances_with_multiple_active_stamps'], 1)
        for key in ('stamp_updates', 'hops', 'media_records', 'reputation_events'):
            self.assertEqual(history[key], 1)
        self.assertEqual(report['new_requests']['with_owner'], 1)
        self.assertEqual(report['authored_letters']['with_writer'], 1)

    def test_json_and_text_do_not_expose_private_values(self):
        for json_output in (False, True):
            output = io.StringIO()
            call_command('audit_letter_sources', as_json=json_output, stdout=output)
            text = output.getvalue()
            for marker in (self.secret, 'private-sentinel@example.org', 'recipient-sentinel@example.org', 'Other private alias', 'Different private body', 'private-sentinel.png'):
                self.assertNotIn(marker, text)
            if json_output:
                report = json.loads(text)
                self.assertEqual(report, collect_audit())
                for key, counts in report.items():
                    if key != 'schema_version':
                        self.assertTrue(all(type(value) is int for value in counts.values()))

    def test_only_read_queries_and_no_record_changes(self):
        models = (get_user_model(), Place, Person, LetterConcept, LetterInstance, LetterRequest, Letter, Stamp, StampUpdate, LetterHop, MediaItem, ReputationEvent)
        before = {model._meta.label: list(model.objects.order_by('pk').values()) for model in models}
        with CaptureQueriesContext(connection) as queries:
            collect_audit()
        for query in queries:
            sql = query['sql'].lstrip().upper()
            self.assertTrue(sql.startswith(('SELECT', 'SAVEPOINT', 'RELEASE', 'BEGIN', 'COMMIT')), sql.split(' ', 1)[0])
        after = {model._meta.label: list(model.objects.order_by('pk').values()) for model in models}
        self.assertEqual(before, after)

    def test_empty_database(self):
        StampUpdate.objects.all().delete()
        MediaItem.objects.all().delete()
        LetterHop.objects.all().delete()
        Stamp.objects.all().delete()
        ReputationEvent.objects.all().delete()
        LetterInstance.objects.all().delete()
        Letter.objects.all().delete()
        LetterRequest.objects.all().delete()
        LetterConcept.objects.all().delete()
        report = collect_audit()
        for key, counts in report.items():
            if key != 'schema_version':
                self.assertTrue(all(value == 0 for value in counts.values()))

    def test_database_error_is_generic_and_produces_no_partial_report(self):
        output = io.StringIO()
        with patch('letters.management.commands.audit_letter_sources.collect_audit', side_effect=OperationalError(self.secret)):
            with self.assertRaises(CommandError) as error:
                call_command('audit_letter_sources', as_json=True, stdout=output)
        self.assertNotIn(self.secret, str(error.exception))
        self.assertEqual(output.getvalue(), '')
