# Production-readiness pass: local validation first

## Status

This first batch adds opt-in production configuration and settings regression
checks. It is not a completed production deployment. Privacy/intake fixes,
workflow tests, shared rate limiting, server installation, HTTPS, backups,
and deployment validation remain separate work.

No migration, account reset, database deletion, dependency upgrade, or EC2
operation is part of this batch. The tracked test database remains tracked;
ignore patterns do not remove it or rewrite its history.

## Local development stays unchanged

Use your existing Python environment and existing settings:

```sh
python manage.py check
python manage.py test deadletter_mailproject.test_settings
python manage.py test
python manage.py runserver
```

If DJANGO_SETTINGS_MODULE is set in your shell, unset it or set it to
`deadletter_mailproject.settings` for local development. Development settings
still honor the existing DJANGO_DEBUG variable.

The settings tests use isolated subprocess imports and do not read or modify
application database records. Application workflow tests should use Django's
isolated test database, never depend on the saved test admin.

Record the commands, environment versions, and results before claiming tests
passed. Tests have not been executed merely because these files are committed.

## Production is explicitly selected

Set DJANGO_SETTINGS_MODULE to
`deadletter_mailproject.settings_production` in the eventual application
service. Required variables:

- DJANGO_SECRET_KEY: unique random key, at least 50 characters and 5 distinct
  characters; never use a test key or commit the real value.
- DJANGO_ALLOWED_HOSTS: exact comma-separated domain names or IP addresses,
  without schemes, paths, or wildcards.

Optional absolute paths:

- DJANGO_DB_PATH (defaults to the existing project db.sqlite3).
- DJANGO_MEDIA_ROOT (defaults to the existing media directory).
- DJANGO_STATIC_ROOT (defaults to staticfiles).

Before actual deployment, put the database and media outside the checkout,
back up the test database, and transfer it deliberately to preserve the admin.
Use a unique admin password rather than a password exposed through a public
test database. No automatic database transfer or initialization is performed.

DJANGO_TRUST_PROXY_HTTPS defaults to false. Enable it only after configuring
a trusted reverse proxy to overwrite X-Forwarded-Proto and blocking direct
backend access. Otherwise HTTPS redirects behind an HTTP backend may loop.
Production always forces DEBUG off and requires secure cookies and HTTPS.
It is not intended for ordinary HTTP local runserver use.

With production variables supplied, inspect production checks separately:

```sh
python manage.py check --deploy --settings=deadletter_mailproject.settings_production
```

Review all warnings. HSTS is deliberately not enabled yet. A clean check is
not proof of deployment safety. Do not run migrations or collectstatic against
production paths until the deployment and backup plan is approved.

## Remaining batches

1. Stop anonymous repeat intake from overwriting existing recipient profiles
   while preserving each new request's prompt.
2. Enforce private-letter policy on public routes and anonymous updates while
   preserving protected staff operations.
3. Add regression tests for these changes, uploads, Markdown, and printing.
4. Validate the branch on the local development machine.
5. Only then prepare and validate the EC2 server and deployment configuration.
