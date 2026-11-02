# Domain refactor: additive foundation

## Status and boundaries
Baseline: 398b9a9; user reported 31 targeted and 88 full-suite tests passing, migration 0007 applied, no site errors. This batch adds LetterRequest, Letter, and nullable LetterInstance.authored_letter only. Tests and migration checks for this batch have NOT been run by the author. Browser/deployment validation NOT performed. No application route, serializer, admin registration, form, workflow, or access behavior changes. This is not the completed refactor or completed participant privacy protection.

## Model responsibilities
LetterRequest is an individual recipient invitation, with original prompt, optional concept classification, separate submitter/owner, delivery context, open state, and requested visibility/restriction/publication storage. Letter is one authored work with optional request/concept, writer, body, explicit prompt/alias/delivery snapshots, and independent visibility/restriction/publication storage. Instances remain physical records with their existing codes and journey relationships. Many letters may answer one request; many instances may reference one letter; standalone drafts are allowed. Nothing automatically closes a request or promotes private prompts into concepts.

Existing LetterConcept rows remain legacy mixed-purpose records until the source audit/backfill and concept-library cutover. The new concept relationships are not an approval to expose historical records. legacy_source is distinct from reusable concept classification and supplies optional one-to-one migration provenance, not ownership proof. No ownership is inferred from existing creator fields, aliases, or email. Snapshot fields are explicitly populated by future migration/services, not automatically synchronized from mutable profiles. Finalized_at stores future finalization state but does not yet enforce an edit lock.

## Compatibility and deletion
Legacy instance body/recipient/concept fields remain authoritative for existing routes in this slice; authored_letter is nullable, non-editable in generated forms, and remains null for all existing rows. There is no dual-write implementation. Do not manually populate new links via raw SQL and expect old views to use them. New owner/writer/restriction/publication fields are non-editable; models are not registered in admin yet to avoid parallel unsafe write paths.

PROTECT intentionally overrides the usual optional-FK SET_NULL convention for Letter.request and LetterInstance.authored_letter: deleting a parent must not silently strip privacy context from a live response/copy. Use a separately designed withdrawal/tombstone service later. Account/recipient/place deletion uses SET_NULL while stored snapshots survive. is_public flags, emails, accounts, stamps, hops, media, and reputation records are untouched. New visibility defaults Participants only and publication defaults false; this alone does not protect legacy public endpoints.

## Migration and local validation
0010_request_letter_foundation creates two new empty tables with audience checks and adds one nullable FK to existing instances. There is NO historical-data backfill in this migration. Separate data migrations follow after mapping ambiguous concept/request records. This batch does not create claims or challenges.

Stop writers and back up the saved database outside the repository before migration operations. Never commit db.sqlite3, backups, or bytecode. Run:
```
git pull --ff-only
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test letters.test_domain_foundation accounts.test_participant_schema accounts.test_email_migration
python manage.py test
```
Expected planned addition: letters.0010_request_letter_foundation when prior migrations are applied. After tests pass and backup is confirmed, run python manage.py migrate. Then check python manage.py migrate --plan and existing admin login, intake, writing desk, read, printing, carry, scan, contact, and leaderboard pages. No new public screens are expected. Tests create isolated data and temporarily migrate the TEST database only.

Reversing 0010 removes the new tables/link and loses any new-model records; it does not restore subsequent data edits. Never use --fake to bypass a mismatch. Git rollback is not a database restore.

## Next bounded batches
1. Read-only aggregate source audit and reviewed historical backfill: preserve original IDs/codes/attribution, one authored letter per historical instance initially, no text deduplication, no automatic public concept promotion or ownership matching.
2. Reusable concept/challenge classification and request/letter creation services, with explicit canonical-source rules.
3. Coordinated workflow/read/admin/template cutover: separate concept library, open request queue, standalone writing/drafts, multiple responses/copies, intended destination snapshots and post-print edit rules.
4. Centralized visibility across HTML/API/printing/stamp/media paths, and retirement/consolidation of stale routing views. Then private request claim storage/redemption and detection/rate-limit work under revised roadmap.
Do not deploy the intermediate schema as a claim of complete privacy. Keep main unchanged and reputation redesign deferred.
