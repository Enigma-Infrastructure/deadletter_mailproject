# Explicit historical backfill: preview, review, then apply

## Scope and status
This is a data-conversion management command, NOT a schema/data migration that runs automatically on migrate. No models, routes, permissions, templates, admin actions or existing fields are changed. Tests in this batch have not been executed by the author. The user's b5a450e checkpoint passed 101 tests. Their local audit contains four recipient-specific concepts and two unlinked instances; a stable unchanged copy should preview four requests and two letters/links. Audit each separate database before assuming those counts apply there.

## Policy
Create one request for each legacy concept with created_for; legacy_source provides unique provenance. Leave recipient-less concepts alone. Create one authored letter per unlinked instance, never deduplicate bodies. A recipient-less concept does not imply a request; its instance becomes a standalone letter. Orphan instances also become standalone letters. Neither requests nor letters gain automatic reusable-concept links. Preserve body text exactly, including blanks and whitespace. Snapshot write_prompt exactly, without falling back to title/description/profile prompt. Request recipient comes from created_for; letter recipient comes from instance.recipient. If a pending instance's recipient differs from or is missing relative to a recipient-specific concept, reject the entire batch before writes.

Use concept destination place/city when a concept exists, including incomplete destinations; do not infer from current physical location. Without a concept, use the recipient's pirate place/city if present. Place city wins when a place is recorded. Destination labels follow the existing name plus middle-dot-city display convention. Snapshots reflect current source values at conversion time, not a claim about unknowable historical profile values. Preserve source created_at on newly created requests and letters; leave finalized_at null. created_by does not prove ownership or authorship: new owner, submitted_by and writer stay null. Existing mappings and authored-letter links are preserved, including reviewed edits; they are not revalidated or repaired by this command.

All new records stay participants_only and unpublished. A hidden legacy instance sets automatically_restricted=True with legacy_hidden reason on its new letter; public legacy flags do not grant publication permission. The legacy flags, bodies, codes, timestamps, printing state and journey relations remain unchanged. Physical instance authored_letter is the only existing-row field updated. Existing target privacy settings are not modified or inherited by new letters. Old workflows remain authoritative; these snapshots are not ongoing dual-write synchronization and may diverge after further legacy edits. Review synchronization before workflow cutover.

## Validation (no source data writes)
Stop the server, workers, admin edits and any other writers to source and target tables. Check git status before pulling; preserve unrelated local work.
```
git pull --ff-only &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_source_backfill letters.test_source_audit letters.test_domain_foundation &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
The command defaults to a read-only JSON preview. --database selects a configured alias for all queries. No new migrations are expected. Output contains fixed field names, mode and aggregate counts only; counts still reveal activity. A conflict produces a generic error without source IDs or private contents.

## Apply separately, after tests and preview review
Make and verify a database backup with your existing database-specific backup process. Keep writers stopped. Only after reviewing the preview, explicitly run:
```
python manage.py backfill_letter_sources --apply &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
For the user's unchanged local audit expect four total new requests, two authored letters and two linked instances after apply; the final preview should plan zero new requests/letters/links. Production values may differ. The write operation is one transaction, row-locks existing source records where supported, conditionally links still-unlinked instances, and rolls back all its writes on failure. Writers must remain stopped: row locks do not protect new inserts, all target edits, or provide universal backend concurrency guarantees. Preview cannot reserve a future plan. Do not apply from an unreviewed database alias.

## Recovery and limitations
No automatic reverse/delete command is supplied: existing target records may acquire edits and other dependencies. On failure the transaction rolls back; review the error and schema, do not fake migrations or reset the database. After a successful apply, restore the reviewed backup only with a database-specific recovery plan and consideration of later writes. Re-running is idempotent for already mapped concepts and linked instances but is not a repair/synchronization mechanism. Missing recipient ambiguity stops the batch; recipient-less concepts remain unclassified. Tests cover preview without SQL writes, atomic rollback, idempotence, existing targets, conflicting/missing recipients, standalone cases, repeated bodies, unanswered requests, privacy, snapshots and preserved physical history. This batch neither deploys nor changes main nor cuts over workflows.
