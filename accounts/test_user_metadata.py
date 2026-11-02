from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TestCase
from .models import User


class UserMetadataTests(SimpleTestCase):
    def test_original_user_names_are_preserved(self):
        self.assertEqual(str(User._meta.verbose_name), 'user')
        self.assertEqual(str(User._meta.verbose_name_plural), 'users')
        self.assertFalse(User._meta.abstract)
        self.assertEqual(User._meta.db_table, 'accounts_user')


class UserMigrationMetadataTests(TestCase):
    def test_live_options_match_recorded_migration_state(self):
        loader = MigrationLoader(connection)
        state = loader.project_state()
        historical = state.apps.get_model('accounts', 'User')
        for name in ('verbose_name', 'verbose_name_plural', 'abstract', 'db_table'):
            with self.subTest(option=name):
                self.assertEqual(str(getattr(User._meta, name)), str(getattr(historical._meta, name)))
