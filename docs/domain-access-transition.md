# Domain workflow transition and child-agent handoff

## Last successful checkpoint: user-local, 2026-11-02
Repository Enigma-Infrastructure/deadletter_mailproject; branch production-readiness. Last validated code: f4bcb2b9b4ec8ca469ba9f6ee5bae46b00507c8e. User reported 32 targeted tests and all 133 tests passing, no system-check issues, model drift or pending migrations. Tests were not independently run by this assistant. Earlier access-adapter baseline 71a7f2f passed 121 tests.

The user's local database was backfilled using 88ec035: four requests, two authored letters, two existing physical instances linked. Latest audit still has four legacy concepts/all mapped, no body disagreement or missing alias/destination snapshots, no new records published, and both physical instances need printing. Final preview plans zero work. These counts are NOT deployment or child-agent database evidence. Backup verification was requested but is not evidenced by terminal output. No further --apply is needed for this local checkpoint.

## Current batch: draft workspace/edit services, not yet validated
Adds letters.domain_drafts and tests; this batch has NOT been executed by the assistant or reported passing by the user yet. No models/migrations/routes/templates/serializers/admin behavior or saved data are changed by committing it. Both write-service modules remain unwired to routes.

Private workspace selectors expose unpublished requests only to their explicit owner, and unpublished letters only to their explicit writer, requiring persisted active approved participation. This is a distinct authorization path from audience/public reads; it is not a staff bypass or permission to traverse parent requests, recipient profiles, addresses, physical history or media. Full returned models are internal, not safe serialization payloads. Finalized unpublished works can appear in the writer workspace but cannot be edited through these services.

edit_request_draft permits prompt/requested-audience changes only for the approved owner, unpublished review_required/automatically_restricted state, no historical source, and no responses. It does not change ownership, snapshots, destination, restriction, publication or open state. Requests with responses require a separate revision workflow.

edit_letter_draft permits body/requested-audience changes only for the approved writer, unpublished/unfinalized review_required state, and exactly one hidden online status=created instance still needing printing. Legacy concept links, divergent bodies, printed/public/other-production states, stamps (including inactive), hops, media or reputation history block edits. It atomically mirrors body into this one staged instance, preserving codes, timestamps, snapshots, attribution and privacy. No revisions/edits of produced copies, synchronization of backfilled rows, or restriction release are supplied. Row locks protect cooperating operations where supported, not arbitrary concurrent admin/courier writes. Unit tests are not HTTP or multiworker concurrency evidence.

## Existing creation-service contracts (validated at f4bcb2b)
letters.domain_writes uses the server-authenticated user and rereads approval/defaults in a transaction. create_request snapshots an active recipient's alias and pirate place/city; inactive recorded destinations reject. Missing places permit incomplete/city-only snapshots for review. owner/submitted_by identify the submitting actor, not ownership of the selected Person identity. No alias/email/legacy-created_by matching; recipient selection/on-behalf UX remains unresolved.

create_response requires active approval plus a published/readable/open request, with no owner/staff unpublished-request bypass. Creates Letter plus physical LetterInstance atomically, snapshots the saved request rather than changed profiles, credits actor as writer, and leaves the request open. Existing reusable-concept link is retained on Letter only, not inferred for physical instance.

All service-created content remains unpublished and automatically restricted with review_required. Requested public preference is not publication permission. Physical drafts are hidden, status=created, origin=online, needs_printing=True, no stamps/printed timestamp. Body is mirrored for staging only. No finalization, personal-data scanner, publication/restriction-release service, or general legacy synchronization exists. Do not merely flip flags to expose or print staged content.

Each successful creation call is a distinct submission even for identical text. No durable idempotency key/HTTP replay protection exists. No automatic retries after ambiguous outcomes; generated-code collisions surface and roll back. Replay protection remains a blocker before routing these services. Legacy/backfilled records are not overwritten. Internal errors/models are not public responses; database errors need generic handling at future boundaries. All services use an explicit database alias. SQLite and noncooperating writers limit locking guarantees.

## Read policy boundaries
letters.access_policy defines pure audience rules; letters.domain_access filters persisted records. Anonymous/inactive/unapproved accounts can read only published public unrestricted content. Approved active accounts can read published restricted content per existing policy. Unknown audiences and unpublished records fail closed for audience reads. Bodies cannot broaden parent-request audience; standalone letters use their own audience.

Staff/superuser/owner/writer/email verification/registration source are not participant approval. Address gates require active approval and readable content. Workspace ownership does not replace those gates. Querysets contain full private models, not field-redacted payloads. Never pass directly to public templates/serializers; body readability does not expose profile emails, address snapshots, media, notes, journeys or tracking codes. Keep legacy is_public route guards; domain audience helpers do not replace them.

Approval is read when a queryset is constructed, not every later evaluation. Build/evaluate within one short request, not across requests/approval changes/caches; use same alias. This is not universal concurrent-revocation protection. Legacy live routes remain authoritative and unchanged; new read/write services are not integrated.

## Validate this batch
Check git status, preserve unrelated work, then:
```
git pull --ff-only &&
git log -1 --oneline &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_drafts letters.test_domain_writes letters.test_domain_access &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
No migrations or saved-data changes expected; no --apply. Unchanged local audit should retain four requests/two letters/two links/no publication/zero backfill work. Test fixtures are separate from saved database data. Tests cover owner/writer workspace, revoked approval, no role bypass, staged edits, immutable fields, physical/history guards, rollback and input rejection.

## Next work and handoff discipline
User requests proceeding directly to the next bounded preparation after a successful run, without a redundant planning question; exact external writes still require approval. Update this checkpoint with actual new results, never label planned tests passed. Coordinate file ownership for child agents; start from current reviewed production-readiness descendant of f4bcb2b, not a blind reset. Report commits/files, executed tests, actual database operations, route changes and risks. No main merge/deploy/backfill application without separate approval.

1. Implement durable replay protection for creation with an explicit schema/unique constraint, actor/operation scoping, payload mismatch rules, transaction/concurrency tests and retention semantics. Do not substitute text deduplication, process-local cache or row locks for idempotency. Keep new routes unwired until resolved.
2. Define recipient/on-behalf ownership, incomplete destination policy, review/publication/restriction release, finalization and optimistic edit conflict handling. Current guarded edits do not provide version tokens; concurrent legitimate edits may be last-writer-wins. Do not claim workspace authorization solves any of these.
3. Inventory all output and write paths: queues/claim/confirmation, browse/desk/detail, print/envelopes, scan GET/POST, carry, API, templates/serializers, admin, media URLs/storage and caches. Add field-redacted presentation objects; search/filter/count must share audience rules. Preserve physical hidden flags, and authorize print/courier actions separately. Test HTTP methods and side effects.
4. Define source of truth and synchronization for legacy edits/new writes without overwriting reviewed target rows. Historical conversion is initial provenance, not synchronization. Only then propose separately reviewed route cutover; unpublished backfilled records would otherwise disappear. This branch is not yet end-to-end participant-private or production-ready.

Related runbooks: docs/source-audit-validation.md and docs/source-backfill-validation.md. Their pre-validation status wording is historical; use this document's last successful checkpoint for latest user-local evidence. Actual contracts live in letters/domain_access.py, letters/domain_writes.py and letters/domain_drafts.py.
