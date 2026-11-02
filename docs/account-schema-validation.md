# Account schema slice: local validation

This slice adds RegistrationSource and six User fields: participant_status,
default_request_visibility, default_body_visibility, registration_source,
participant_reviewed_by, and participant_reviewed_at. It does not implement
registration pages, review actions, policy adapters, request/body privacy
storage, claiming, media protection, or route enforcement.

Existing accounts receive pending participant status and Public preferences
for future submissions. Their login credentials, activity status, staff and
superuser flags remain unchanged. Admin access is not participant approval.
No source code auto-approves a user. Account choices are validated by Django
model/form validation, not database CHECK constraints in this slice.

The existing content is not modified, reclassified, deleted, or assigned an
owner. Historical content privacy backfills follow separately. Preferences
do not grant access or make historical content public. The existing tests
still exercise existing routes, not a completed new access model.

## Before applying migrations to the saved database

Stop runserver. Back up db.sqlite3 to a location OUTSIDE the public repository
while the database is not being written. Preserve that backup until the
whole feature is validated. Do not commit the database or backup.

Pull this branch, then run against the isolated test database first:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test accounts.test_participant_schema --verbosity 2
python manage.py test --verbosity 2
python manage.py migrate --plan
```

There are seven new test methods. The migration test temporarily changes
the TEST database schema and restores current migration leaves in finally.
It never targets the saved development database when run with Django's
standard test runner. Tests are not claimed passed until executed.

After those pass and the plan shows the expected accounts migration:

```sh
python manage.py migrate
python manage.py runserver
```

Verify existing admin login and the ordinary local submission workflow.
Do not register pending participant state as a replacement for admin access.
Reversing the schema migration removes the NEW preference/review/source
information; it does not recover later user decisions. Back up before
rollback, and use the original backup if full restoration is required.

The existing User model was already absent from accounts/admin.py; this
slice does not alter admin registration or add approval screens yet.
