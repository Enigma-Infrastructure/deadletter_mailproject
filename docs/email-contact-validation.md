# Account email/intake pass: sub-batch 1 of 2

## Status
Account-contact implementation and tests supplied; Django tests, migration checks, and browser checks NOT run by author. No deployment validation. This is NOT the complete email/intake pass. Sub-batch 2 must remove request email collection, update existing recipient-intake tests without losing historical preservation coverage, preserve Person.email, and add truthful anonymous post-submission Register/Log in prompts. Until then the existing intake email field remains.

## Behavior
Optional registration email uses existing User.email, stays non-unique, and never grants approval or subscription consent. /accounts/contact/ is linked from Preferences. It requires login and current password for every contact save, supports blank removal, is never cached, and does not accept user IDs/verification/approval as editable fields. Pending/rejected/suspended active accounts may manage contact details. No confirmation email/token or request ownership workflow is supplied.

EmailStateMixin is abstract and contributes only email_verified to User. New/existing accounts default false. Ordinary model saves cannot mark verified. Existing-address saves retain persisted verification, changed/blank email clears it, and stale full saves with unchanged locally loaded email retain current persisted contact state. Explicit update_fields isolates unrelated writes. Admin email edits use this same rule. QuerySet.update, bulk_update, raw SQL, and external database writes bypass model hooks and are NOT supported contact-edit paths. A future verified-token service needs a deliberate restricted write path. Exact-address changes, including case changes, invalidate verification.

All four Django password-reset endpoint patterns are shadowed by account URLs and return a generic 503 unavailable page for GET/POST. Login/logout/password-change URLs remain unchanged. No email is sent and no password is changed by these recovery routes. This prevents unverified account contact storage from implicitly enabling email recovery. No uniqueness, email login, legacy-email matching, newsletter, letter permission, reputation, or claim changes.

## Migration
0007_user_email_verified depends on accounts.0006_participant_preferences and adds only email_verified default false editable false. Existing emails, passwords, approval/admin flags and legacy Person data are not rewritten. Before applying to saved db.sqlite3, stop writes and back up outside the repository. Never commit database or backup. Rollback removes verification state, not account email edits; Git rollback is not database rollback.

Run isolated tests first:
```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test accounts.test_email_contact accounts.test_email_migration accounts.test_participant_schema
python manage.py test
```
After reviewing outputs and backup, apply locally with python manage.py migrate. Expected new account migration is 0007, plus any genuinely pending dependencies.

Browser-check registration with/without/invalid email, Preferences -> Manage contact email, missing/wrong/current password, unchanged/new/removed address, blank/unverified status, admin read-only verification/filter and email edit, and all unavailable recovery routes. Confirm card layout, existing login/logout, and preserved admin access. No claims of local/browser success until results are recorded.

## Previous checkpoint
User reported 3343f7d passed system checks, no model changes/pending migrations, 24 targeted tests, 74 full-suite tests, and no observed site issues. This does not validate the present migration-bearing change. Reputation backlog remains deferred.
