# Email framework: User metadata correction

The user ran checks after ba45530. System checks passed, but makemigrations --check --dry-run reported an unintended 0008_alter_user_options. The chained migration-plan and test commands did not run. Dry-run does not create the proposed migration file. No tests from that run are claimed passed.

Cause: User now inherits EmailStateMixin before AbstractUser; the first abstract base's Meta supplied no verbose_name/verbose_name_plural. accounts.0001_initial records user/users. Restore those names in the mixin's abstract Meta rather than accepting an unrelated metadata migration. No database/data changes or migration edits are included in this correction. Regression tests compare live names/options with recorded migration state.

Validation NOT run by author. Run after pull:
```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test accounts.test_user_metadata accounts.test_email_contact accounts.test_email_migration accounts.test_participant_schema
python manage.py test
```
Expected: no model drift and only accounts.0007_user_email_verified pending if 0006 is applied. Back up saved database outside repository before applying 0007. Do not generate/fake 0008 to bypass this issue. If an actual local 0008 was created separately, inspect its contents and application status before taking any action.

This correction does not complete email/intake sub-batch 2, apply migrations, validate browser rendering, or authorize deployment.
