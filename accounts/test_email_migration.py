from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class EmailMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_accounts_and_unverifies_everyone(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [('accounts', '0006_participant_preferences')]
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            User = apps.get_model('accounts', 'User')
            account = User.objects.create(username='legacy-email-admin', email='legacy@example.org', password='preserved-hash', is_staff=True, is_superuser=True, is_active=True, participant_status='approved')
            executor = MigrationExecutor(connection)
            target = [('accounts', '0007_user_email_verified')]
            executor.migrate(target)
            User = executor.loader.project_state(target).apps.get_model('accounts', 'User')
            updated = User.objects.get(pk=account.pk)
            self.assertEqual(updated.email, 'legacy@example.org')
            self.assertEqual(updated.password, 'preserved-hash')
            self.assertTrue(updated.is_staff and updated.is_superuser and updated.is_active)
            self.assertEqual(updated.participant_status, 'approved')
            self.assertFalse(updated.email_verified)
        finally:
            MigrationExecutor(connection).migrate(latest)
