from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import RegistrationSource


class ParticipantSchemaTests(TestCase):
    def test_new_user_defaults_do_not_grant_approval_or_staff(self):
        user = get_user_model().objects.create_user(username="new", password="test-password")
        self.assertEqual(user.participant_status, "pending")
        self.assertEqual(user.default_request_visibility, "public")
        self.assertEqual(user.default_body_visibility, "public")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_approval_does_not_grant_staff_or_change_password(self):
        user = get_user_model().objects.create_user(username="participant", password="test-password")
        original = user.password
        user.participant_status = "approved"
        user.save(update_fields=["participant_status"])
        user.refresh_from_db()
        self.assertEqual(user.password, original)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_source_availability_respects_expiry_and_active_status(self):
        now = timezone.now()
        source = RegistrationSource(code="event-table", label="Event table")
        self.assertTrue(source.is_available(at=now))
        source.expires_at = now
        self.assertFalse(source.is_available(at=now))
        source.expires_at = now + timedelta(hours=1)
        self.assertTrue(source.is_available(at=now))
        source.is_active = False
        self.assertFalse(source.is_available(at=now))

    def test_source_never_auto_approves_and_deletion_preserves_user(self):
        source = RegistrationSource.objects.create(code="event", label="Event")
        user = get_user_model().objects.create_user(username="visitor", registration_source=source)
        self.assertEqual(user.participant_status, "pending")
        source.delete()
        user.refresh_from_db()
        self.assertIsNone(user.registration_source)
        self.assertEqual(user.participant_status, "pending")

    def test_review_metadata_is_independent_of_admin_privileges(self):
        reviewer = get_user_model().objects.create_superuser(username="reviewer", password="test-password")
        user = get_user_model().objects.create_user(
            username="reviewed", participant_status="approved",
            participant_reviewed_by=reviewer, participant_reviewed_at=timezone.now(),
        )
        reviewer.delete()
        user.refresh_from_db()
        self.assertIsNone(user.participant_reviewed_by)
        self.assertIsNotNone(user.participant_reviewed_at)
        self.assertFalse(user.is_staff)

    def test_model_validation_rejects_unknown_choices(self):
        user = get_user_model()(username="invalid", participant_status="unknown")
        with self.assertRaises(ValidationError):
            user.full_clean()


class ParticipantMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_existing_accounts_and_credentials(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [("accounts", "0005_reputation")]
        try:
            executor.migrate(old)
            historical = executor.loader.project_state(old).apps.get_model("accounts", "User")
            admin = historical.objects.create(
                username="historical-admin", password="preserved-password-hash",
                is_active=True, is_staff=True, is_superuser=True,
            )
            ordinary = historical.objects.create(username="historical-user", password="another-hash", is_active=True)
            executor = MigrationExecutor(connection)
            target = [("accounts", "0006_participant_preferences")]
            executor.migrate(target)
            upgraded = executor.loader.project_state(target).apps.get_model("accounts", "User")
            admin = upgraded.objects.get(pk=admin.pk)
            ordinary = upgraded.objects.get(pk=ordinary.pk)
            self.assertEqual(admin.password, "preserved-password-hash")
            self.assertTrue(admin.is_active and admin.is_staff and admin.is_superuser)
            self.assertEqual(admin.participant_status, "pending")
            self.assertEqual(ordinary.password, "another-hash")
            self.assertEqual(ordinary.participant_status, "pending")
            self.assertFalse(ordinary.is_staff or ordinary.is_superuser)
            self.assertEqual(ordinary.default_request_visibility, "public")
            self.assertEqual(ordinary.default_body_visibility, "public")
        finally:
            MigrationExecutor(connection).migrate(latest)
