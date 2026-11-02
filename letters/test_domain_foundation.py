from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase

from people.models import Person, Place
from .models import Letter, LetterConcept, LetterInstance, LetterRequest


class DomainFoundationTests(TestCase):
    def test_safe_defaults_and_standalone_draft(self):
        request = LetterRequest.objects.create(prompt='An invitation')
        letter = Letter.objects.create(body_text='A standalone draft')
        for obj in (request, letter):
            self.assertEqual(obj.requested_visibility, 'participants_only')
            self.assertFalse(obj.is_published)
            self.assertFalse(obj.automatically_restricted)
        self.assertIsNone(request.owner_id)
        self.assertIsNone(request.submitted_by_id)
        self.assertIsNone(letter.request_id)
        self.assertIsNone(letter.finalized_at)

    def test_reusable_concept_multiple_responses_and_copies(self):
        concept = LetterConcept.objects.create(title='Home')
        request = LetterRequest.objects.create(prompt='My question', concept=concept)
        first = Letter.objects.create(request=request, concept=concept, body_text='First response')
        second = Letter.objects.create(request=request, concept=concept, body_text='Second response')
        a = LetterInstance.objects.create(authored_letter=first, status='traveling')
        b = LetterInstance.objects.create(authored_letter=first, status='delivered')
        self.assertEqual(request.responses.count(), 2)
        self.assertEqual(first.instances.count(), 2)
        self.assertNotEqual(a.code, b.code)
        self.assertNotEqual(a.status, b.status)
        self.assertEqual(concept.authored_letters.count(), 2)
        self.assertTrue(request.is_open)
        self.assertEqual(second.instances.count(), 0)

    def test_requested_audience_does_not_clear_restriction(self):
        request = LetterRequest.objects.create(automatically_restricted=True, restriction_reason='review_required')
        request.requested_visibility = 'public'
        request.save(update_fields=['requested_visibility'])
        request.refresh_from_db()
        self.assertTrue(request.automatically_restricted)
        self.assertEqual(request.restriction_reason, 'review_required')

    def test_visibility_constraints(self):
        for model in (LetterRequest, Letter):
            with self.subTest(model=model.__name__):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        model.objects.create(requested_visibility='friends')

    def test_parent_deletion_cannot_drop_privacy_context(self):
        request = LetterRequest.objects.create()
        letter = Letter.objects.create(request=request)
        instance = LetterInstance.objects.create(authored_letter=letter)
        with self.assertRaises(ProtectedError):
            request.delete()
        with self.assertRaises(ProtectedError):
            letter.delete()
        self.assertTrue(LetterInstance.objects.filter(pk=instance.pk).exists())

    def test_owner_is_distinct_from_writer_and_account_contact(self):
        User = get_user_model()
        owner = User.objects.create_user(username='request-owner', email='private@example.org')
        writer = User.objects.create_user(username='letter-writer')
        request = LetterRequest.objects.create(owner=owner)
        letter = Letter.objects.create(request=request, writer=writer)
        self.assertNotEqual(request.owner_id, letter.writer_id)
        owner.delete()
        request.refresh_from_db()
        letter.refresh_from_db()
        self.assertIsNone(request.owner_id)
        self.assertEqual(letter.writer_id, writer.pk)
        self.assertFalse(request.is_published)

    def test_explicit_snapshots_survive_profile_changes(self):
        place = Place.objects.create(name='Original Cafe', city='Somerville')
        person = Person.objects.create(nickname='Original Alias', pirate_place=place)
        letter = Letter.objects.create(recipient=person, recipient_alias='Original Alias', destination_place=place, destination_label='Original Cafe · Somerville', prompt_snapshot='Original inspiration')
        person.nickname = 'Changed Alias'
        person.save(update_fields=['nickname'])
        place.name = 'Changed Cafe'
        place.save(update_fields=['name'])
        letter.refresh_from_db()
        self.assertEqual(letter.recipient_alias, 'Original Alias')
        self.assertEqual(letter.destination_label, 'Original Cafe · Somerville')
        self.assertEqual(letter.prompt_snapshot, 'Original inspiration')


class DomainFoundationMigrationTests(TransactionTestCase):
    def test_schema_upgrade_preserves_legacy_data_without_guessing(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [('letters', '0009_auto_20260928_1638'), ('accounts', '0007_user_email_verified')]
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            User = apps.get_model('accounts', 'User')
            Concept = apps.get_model('letters', 'LetterConcept')
            Instance = apps.get_model('letters', 'LetterInstance')
            Stamp = apps.get_model('letters', 'Stamp')
            Hop = apps.get_model('letters', 'LetterHop')
            user = User.objects.create(username='preserved-organizer', password='preserved-hash', is_staff=True, is_superuser=True)
            concept = Concept.objects.create(title='Legacy request or concept', write_prompt='Preserve original prompt')
            instance = Instance.objects.create(concept=concept, body_text='Preserve original body', code='KEEP-CODE', is_public=False, created_by_id=user.pk)
            stamp = Stamp.objects.create(letter_id=instance.pk, number='KEEPSTAMP')
            hop = Hop.objects.create(letter_id=instance.pk, notes='Preserve journey')
            executor = MigrationExecutor(connection)
            target = [('letters', '0010_request_letter_foundation'), ('accounts', '0007_user_email_verified')]
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            upgraded = apps.get_model('letters', 'LetterInstance').objects.get(pk=instance.pk)
            self.assertEqual(upgraded.code, 'KEEP-CODE')
            self.assertEqual(upgraded.body_text, 'Preserve original body')
            self.assertFalse(upgraded.is_public)
            self.assertEqual(upgraded.created_by_id, user.pk)
            self.assertIsNone(upgraded.authored_letter_id)
            self.assertEqual(apps.get_model('letters', 'LetterConcept').objects.get(pk=concept.pk).write_prompt, 'Preserve original prompt')
            self.assertEqual(apps.get_model('letters', 'Stamp').objects.get(pk=stamp.pk).letter_id, instance.pk)
            self.assertEqual(apps.get_model('letters', 'LetterHop').objects.get(pk=hop.pk).notes, 'Preserve journey')
            self.assertEqual(apps.get_model('accounts', 'User').objects.get(pk=user.pk).password, 'preserved-hash')
            self.assertEqual(apps.get_model('letters', 'LetterRequest').objects.count(), 0)
            self.assertEqual(apps.get_model('letters', 'Letter').objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
