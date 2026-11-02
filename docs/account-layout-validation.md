# Account and admin-hub layout completion

## Scope and status
This batch repairs preferences, participation status, and the custom admin hub using the existing single-card layout. Login and registration were already repaired in 02984ca. Shared CSS, info-page wording, permissions, routes, and models are unchanged. No migrations. Tests supplied but NOT executed by the author. Browser and deployment validation NOT performed.

## Hub destination coverage
The hub links to Django admin index; participant review; registration sources; request intake; writing desk; carry list; scan landing; leaderboard; and model administration for people, places, concepts, instances, stamps, stamp updates, hops, topics, and media. The new test enumerates the actual hub sections and GETs every linked destination as a superuser, following redirects. Another test opens the account/source/domain admin add forms. These are rendering smoke tests, not screenshot or browser-layout tests. They do not exercise every edit/delete/history screen or populated-data edge case.

The inspected request, carry, scan, and leaderboard templates already have card/desk containers. Django admin destinations use Django's own admin templates and stylesheet, not the public site's main/card layout; do not wrap those in the public card or override admin CSS indiscriminately. Existing desk and browse layouts retain their intentional structures. Do not claim all destination layouts visually passed without browser checks.

## Validation required
```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test accounts.test_account_layout accounts.test_navigation accounts.test_registration accounts.test_participant_review accounts.test_preferences
python manage.py test
```

Browser-check preferences and each participation status, login/register errors, admin hub sections, and every hub link at desktop and narrow widths. Review model list/add/change screens using local sample records, long values, validation errors, and filter controls. Check desk/carry/scan/request/leaderboard without changing their behavior. Browser coverage remains pending until results are recorded.

## Roadmap addendum
Read with docs/participant-roadmap.md; this addendum records the expanded layout scope. After this repair is locally validated, propose a separate email/intake foundation batch: reuse User.email, optional registration email and account-contact editing, email_verified default false, server-side invalidation when email changes, read-only admin verification display/filter, removal of new intake email collection, preservation of historical Person.email, and a truthful anonymous confirmation Register/Log in prompt. Do not auto-copy legacy emails, infer ownership, approve participation, claim email consent, or offer nonfunctional verification. Actual outbound verification and secure request linking remain separate workflows. Then continue A2, C, D, E, F, G per participant-roadmap.md.

No main merge, EC2 deployment, database reset, or automatic email verification is authorized by this layout batch.
