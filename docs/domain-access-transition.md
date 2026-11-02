# Domain workflow transition and child-agent handoff

## Last successful checkpoint: user-local, 2026-11-02
Repo Enigma-Infrastructure/deadletter_mailproject; branch production-readiness. Last user-validated code 348c49fd11f0a4e514c66fea086945b0a19d5e88: all 35 targeted and all 147 tests passed; no system issues, model drift or pending migrations. Assistant did not independently execute tests. Earlier f4bcb2b validated staged creation at 133 tests; 71a7f2f validated persisted audience adapters at 121 tests.

User-local data: four requests, two authored letters, two existing physical instances linked by the backfill from 88ec035; four legacy concepts/all mapped; no body differences or missing alias/destination snapshots; no new records published; two instances need printing. Final preview plans zero work. Not evidence of deployment/child-agent DB state. Backup verification requested previously but not evidenced by terminal output. Do not rerun backfill --apply for this checkpoint.

## Current batch: durable replay, NOT yet validated or applied
Adds DomainSubmissionReceipt and schema-only letters.0011_domain_submission_receipt, staged letters.domain_submissions wrappers and tests. No routes/templates/serializers/admin changes, automatic backfill, publication or live workflow switch. Migration has NOT been applied by assistant; new tests have NOT been executed or reported passing. No existing model field is intended to change. A model-drift check must show no additional migrations.

Use submit_request/submit_response with server-authenticated user and a fresh random UUID4 per intentional submission; reuse the SAME key and exact input for transport retries. UUID spellings normalize. Unique DB constraint scopes a SHA256 key digest by actor and operation (request/response). HMAC-SHA256 canonical versioned payload stores no raw key/prompt/body in receipts. Submitted None audience remains a sentinel rather than changing fingerprint with account defaults; explicit audience versus None are different inputs. Rotating SECRET_KEY makes old payload fingerprints mismatch and fail closed; review operational rotation before route rollout. Do not log keys/payloads/digests or treat receipts as public API objects.

Receipt reservation, creation and completion share one transaction. Existing actor row is locked where supported and DB uniqueness is authoritative. Identical replay returns existing IDs/current objects and replayed=True, not an immutable HTTP response. Changed input rejects without overwrite. Actor approval is rechecked even on replay; existing-result owner/writer must still match. A now-closed/unpublished parent does not create new work on replay; the writer's own prior result is returned privately. Deleted/missing result IDs remain tombstones and reject instead of recreating. Incomplete persisted receipts fail closed. Response wrapper returns (letter, instance, replayed); request wrapper returns (request, replayed).

No automatic receipt expiry/cleanup is supplied: retain for account lifetime. Target deletion sets result FKs null, retaining tombstones. Account deletion cascades its receipts; guarantees do not survive deliberate receipt removal, schema reversal, DB restore or account deletion. Raw hashes are not anonymization. Migration reversal removes receipts and replay guarantees without undoing created content; do not reverse casually after use. Backend lock/serialization errors propagate; future boundaries must return generic errors and retry only with same key/payload. SQLite concurrency may return locked/busy; test on deployment backend before claiming multiworker readiness. The concurrent two-worker test is skipped without select_for_update support. Low-level domain_writes stays deliberately non-idempotent: future routes must use wrappers, not bypass them.

## Creation, draft and privacy contracts already implemented
Creation requires persisted active approved actor, never staff/owner/email status as approval. Request owner/submitted_by are submitter, NOT ownership of Person identity; active recipient/place snapshots, missing-place/incomplete destination and on-behalf UX still need policy. Response requires published/readable/open parent; snapshots saved request, creates letter/hidden physical instance atomically; credits writer; leaves parent open; no inferred legacy concept links on physical instance. Same text with different keys is separate work.

Service-created records stay unpublished/automatically_restricted review_required; public preference is not permission to publish. Physical drafts hidden/status=created/origin=online/needs_printing=True/no stamps. No publication/restriction-release, scanner, finalization or general legacy synchronization. Do not merely flip flags to print/expose drafts.

Workspace selectors require active approval and explicit request owner/letter writer for unpublished records. Separate from public audience reads, no role bypass, not permission to traverse parent/profile/address/history/media. Finalized unpublished letters may appear but cannot edit. Request edit permits prompt/audience only for unpublished review_required owner, no historical source or responses. Letter edit permits body/audience only for unpublished/unfinalized review_required writer, exactly one hidden unprinted online status=created instance without legacy concept, divergent body or any stamp/hop/media/reputation history. Body mirrors atomically; preserve codes/snapshots/identity/restriction. No version token: legitimate concurrent edits can be last-writer-wins. Noncooperating admin/courier writes are not protected universally.

Audience adapters fail closed on unknown visibility/unpublished records; approved readers may read published restricted content under current pure policy. Parent bounds body audience; standalone letters use own audience. Address requires approval plus readable content; workspace ownership does not grant addresses. Full models/querysets are not redacted payloads. Never expose directly via public serializers/templates; keep legacy is_public guards. Approval captured at queryset construction; evaluate within short request, not across caches/revocation. All services use explicit DB alias. Live legacy behavior remains unchanged and authoritative.

## Validate code before applying schema to saved database
Preserve unrelated git work, then:
```
git pull --ff-only &&
git log -1 --oneline &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_submissions letters.test_domain_drafts letters.test_domain_writes &&
python manage.py test
```
Expect exactly pending letters.0011 (plus any separately known prerequisites), no unexpected drift. Tests use their own DB and apply migration there. Review any skips; select_for_update concurrency test is not exercised on SQLite. If code tests pass, make/verify a DB-specific backup, stop writers and separately approve/apply schema:
```
python manage.py migrate &&
python manage.py migrate --plan &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
No --apply backfill. Migration creates receipt table only; unchanged local counts should remain four requests/two letters/two links/no publication/zero backfill work. Never fake migrations/reset DB. Committing code is not consent to apply schema or deploy. Tests cover scoped uniqueness, replay/mismatch, edits/default changes, revoked approval, rollback, deleted results, private receipt contents, schema preservation and conditional concurrency.

## Next steps and delegation
User prefers direct next bounded preparation after successful run, not redundant planning questions. Exact external writes still require approval. Record actual results, not planned tests as passed. Start child agents from current reviewed production-readiness descendant of 348c49f; coordinate file ownership, preserve unrelated changes, report commits/files/tests/skips/DB operations/route changes/risks. No main merge/deploy/backfill/schema execution without separate approval.

1. Validate replay batch and schema separately. Test deployment backend concurrency and define retry/error/retention/secret-rotation behavior before HTTP wiring.
2. Add field-redacted presentation objects and optimistic edit conflict tokens; settle recipient selection/on-behalf identity and incomplete addresses. Define review/publication/restriction release and finalization.
3. Inventory all routes/outputs: queue/claim/confirmation, browse/desk/detail, print/envelope, scan GET/POST, carry, API, templates/serializers, admin, media storage/URLs and caches. Search/filter/count share audience. Authorize printing/courier effects separately; preserve physical hidden flags and test HTTP methods.
4. Define source of truth and synchronization for legacy edits without overwriting reviewed targets. Backfill is provenance, not synchronization. Only then separate reviewed workflow cutover; current backfilled content is unpublished. Not yet end-to-end participant-private or production-ready.

Related docs/source-audit-validation.md and docs/source-backfill-validation.md contain historical pre-validation wording; current checkpoint above supersedes status only, not their operational cautions. Actual contracts: letters/domain_access.py, domain_writes.py, domain_drafts.py, domain_submissions.py. Update this handoff with each new observed checkpoint.
