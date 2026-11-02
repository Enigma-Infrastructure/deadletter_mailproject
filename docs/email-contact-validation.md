# Account email/intake pass

## Recorded checkpoints
At 407293d, the user reported no model drift, the expected accounts.0007 plan, 17 targeted tests passing and 84 full-suite tests passing. The user subsequently confirmed migration 0007 applied successfully with no site errors. These are user-reported local results, not author-executed tests, and do not validate the present sub-batch 2 patch.

## Scope
Sub-batch 1 implements optional User.email at registration, email_verified false by default, guarded /accounts/contact/ linked from Preferences, current-password checks, verification invalidation, read-only admin verification/filter, and unavailable email-recovery routes. Sub-batch 2 removes email from public request form/template and intake persistence, preserves historical Person.email, and adds anonymous Register/Log in options or signed-in account-contact links after submission. Both implementations are supplied after this commit, but sub-batch 2 tests/browser checks are NOT run by the author and deployment is NOT validated.

Email addresses remain optional and non-unique. No verification emails, tokens, notifications, newsletter subscriptions, email login, recipient-email copying, request ownership, or claim credentials are implemented. Registration and login do not retroactively claim submissions. The confirmation page explicitly says linking is unavailable. Signed-in requests also remain unlinked until the ownership batch. Existing request prompt/profile non-overwrite behavior and postal-address validation are retained. Unknown legacy email POST parameters are ignored, not stored or reflected; invalid request tests now use an actual required-field failure rather than validating a removed email field. Existing privacy tests remain intact.

## Email state write boundary
EmailStateMixin contributes email_verified and preserves original User metadata. Ordinary saves cannot mark verified; a changed/blank email clears it, same-address saves preserve persisted state, and unchanged locally loaded email on stale full saves retains current persisted contact state. update_fields isolates unrelated writes. Admin edits use this rule. QuerySet.update, bulk_update, raw SQL, and external writes bypass hooks and are NOT supported contact-edit paths. Future token verification needs a restricted deliberate write path. Exact-address changes including case changes invalidate verification.

## Migration
Only accounts.0007_user_email_verified adds schema for this overall pass. Sub-batch 2 adds NO migrations and changes NO historical data. Never reset the database, fake migrations, or commit db.sqlite3/backups. Reversal of 0007 removes verification state, not subsequent email edits.

## Validate sub-batch 2
```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test letters.test_privacy_intake accounts.test_email_contact accounts.test_email_migration accounts.test_user_metadata accounts.test_account_layout
python manage.py test
```
Expect no new migration or pending operations if 0007 is applied. Browser-check anonymous intake with no email field, required-field/postal validation and override, anonymous confirmation account links and limitations, registration with/without email, and signed-in confirmation contact links. Verify historical recipient emails remain unchanged using organizer access without exposing them on confirmation. Check desktop/narrow layout, original info-page copy, existing admin login, and contact edit/remove with current password. No mail should be sent or promised.

## Next
Proceed to A2 content/privacy and request-specific claim storage, then C enforcement and D ownership/claim workflows under docs/participant-roadmap.md. Do not mislabel this account invitation as a completed claim flow. Reputation redesign remains deferred under docs/reputation-backlog.md. No merge to main, EC2 deployment, access broadening, or legacy ownership matching is authorized.
