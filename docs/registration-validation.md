# Batch B: registration, review, preferences

## Status
Implementation and tests supplied. Django checks, targeted tests, full suite, migration checks, and browser checks have NOT been executed by this change's author. Deployment is NOT validated. No migrations or schema changes are included. Do not merge to main or deploy to EC2 before integrated local validation passes.

## Behavior
Registration starts pending, signs the new account in, and redirects to /accounts/status/. Defaults start Public under the agreed policy. Source is optional attribution only: QR GET parameter source prepopulates the form; submitted manual value wins, including blank removal. Invalid, inactive, or expired supplied codes produce a field error. Source availability is rechecked inside the registration transaction. Approval/admin fields are not registration inputs.

/accounts/preferences/ changes only the current account's two future-submission defaults. It does not update content or implement submission-form integration, which belongs to Batch C. /accounts/status/ works for pending, rejected, and suspended active accounts too. Participant suspension deliberately does not change Django is_active.

The Django user admin is the review queue: filter by participant_status and registration_source; select accounts and use explicit approve/reject/suspend actions. Review requires an active staff user with accounts.change_user; participant status alone is insufficient. Status, attribution, and review metadata are read-only on the edit form. Review actions record reviewer/time and admin change logs without changing administrative flags. Source administration uses normal Django model permissions. Existing reputation administration is retained.

viewer_for_user rereads persisted active/approval state and adapts it to the existing pure policy. It is not automatically wired into legacy content routes. Revocation tests cover the adapter and status screen with an existing session, not application-wide route protection. Organizer-hidden content and request/body restrictions remain governed by the existing policy.

Claim issuance/redemption is deferred to Batch D. Registration does not clear unrelated session keys or infer ownership from sources, aliases, or email. This is not a claim-preservation implementation or test. Login redirects and existing letter routes are unchanged. No rate limiter is introduced in this batch.

## Local validation required
Back up db.sqlite3 before local migration operations. Do not commit a modified database.

```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test accounts.test_registration accounts.test_participant_review accounts.test_preferences
python manage.py test
```

Browser checks: visit /accounts/register/ anonymously; verify Public defaults and privacy explanations; register without a source and verify pending signed-in state; repeat in a fresh browser with ?source=<active-code>, a manual override, and invalid/expired/inactive sources. Verify password errors and CSRF rejection. In /admin/accounts/user/, filter source/status, approve/reject/suspend the account, and verify /accounts/status/ changes in its already logged-in browser. Confirm approved accounts cannot enter admin, and reviewers without change_user cannot run actions. Change preferences and verify no existing request/body changes. Confirm existing organizer login, reputation admin, auth URLs, and letter routes still work.

Record actual outputs and browser results before describing this batch as tested locally. Application-wide visibility enforcement remains Batch C.
