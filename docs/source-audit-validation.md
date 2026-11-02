# Read-only source audit before historical backfill

## Baseline and scope
User reported 35828b9 passed system checks, no model drift/pending operations, 16 targeted tests and all 96 tests; letters.0010 was applied successfully. This batch adds a read-only management command and tests only. It does not backfill, classify, publish, claim, merge, or change any records, routes, templates, permissions, or schema. Tests for this batch have NOT been run by the author.

## Run locally
Stop runserver/other writers so the counts describe a stable dataset. No backup is needed specifically to run this read-only inventory, but preserve backups before any subsequent data migration.
```
git pull --ff-only &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_source_audit letters.test_domain_foundation &&
python manage.py test &&
python manage.py audit_letter_sources --json
```
No new migrations are expected. Output contains a version and aggregate integer counts only. It omits IDs, codes, usernames, emails, aliases, locations, prompts, bodies, notes, filenames, and database paths. Counts can still reveal project activity; share deliberately rather than treating aggregates as automatically anonymous. No external network calls or filesystem exports are performed. --database selects a configured database alias; omitted means default. For human-readable output omit --json.

The implementation uses ORM aggregate/count queries and transaction.atomic to group reads, not to grant a universal cross-backend snapshot guarantee. Stop writers for consistent review. Tests verify fixture counts, absence of private markers in JSON/text, no data changes, SELECT/transaction-only queries, empty-data behavior, and generic database errors. A missing schema/database error returns no partial report; apply reviewed prerequisites rather than faking migrations.

## Interpret before approving a backfill
Concepts with recipients may be requests, but that is evidence for review rather than identity/ownership proof. Concepts without recipients may be reusable inspiration or incomplete records. Empty body means exactly an empty string; whitespace-only content is counted as nonempty. Multiple instances may be multiple authored responses or copies; do not text-deduplicate or assume one work. Missing relationships are not necessarily corrupt records. Conflicting recipients require an explicit precedence rule or review; do not silently overwrite one. Printed/needs_printing disagreement and multiple active stamps are observations, not automatic repair instructions.

New-model/link counts must be reviewed before a backfill: it must not overwrite existing Letter/LetterRequest rows or reassign linked instances. Any source mapping should preserve provenance and be idempotent. Owner/writer counts are existing metadata only; no accounts are matched by alias/email. Legacy is_public flags do not establish permission to publish reusable concepts. Distinct concept links carry no permission inheritance.

## Next pass
Review the count report, then propose a separate historical-data migration with tests and explicit handling of ambiguous sources, snapshots, hidden flags, existing links, one initial authored letter per legacy instance, and preserved codes/journeys. Keep old routes authoritative until the coordinated workflow/privacy cutover. No site redesign, main merge, deployment, database reset, or reputation redesign is part of this audit.
