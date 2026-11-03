# Domain workflow transition and child-agent handoff

## Last confirmed checkpoint: user-local, 2026-11-03
Repository Enigma-Infrastructure/deadletter_mailproject; branch production-readiness. Validated source 2dec5d6: admin changelists, Admin Hub domain links, and serializer tests passing cleanly.

## Current batch: Roadmap Items E & F (Server-side content screening and shared rate limiting)
Consolidated safety and abuse prevention pass:
1. Sensitive Content Screening (letters/content_screening.py): Deterministic, server-side pattern screening for PII (phones, emails, SSNs, credit cards), external spam URLs, and prohibited harassment terms without external AI transmission or private text mangling/logging.
2. Workflow Integration: Flagged intake requests and desk letters automatically set automatically_restricted=True and is_published=False, routing them to the staff review queue before print or public release.
3. Shared Account-Aware Rate Limiting (letters/ratelimit.py): Cache-backed rate limiting utility keying on user IDs for authenticated accounts and client IPs for anonymous visitors, protecting intake, desk authoring, registration, and scans.
4. Automated Tests: letters/test_screening_and_ratelimit.py covering unit pattern recognition, intake auto-restriction, claim hold cascade, and cache rate limit enforcement.

request_draft_snapshot/letter_draft_snapshot require persisted active approved owner/writer and unpublished record. Return a private envelope {card, edit_token}; card keeps existing field allowlists. Snapshot retrieval uses a transaction/row locks where supported, but performs no SQL data writes. Snapshot availability is not a guarantee of editability: finalization, history and other guards can still prevent saves.

Signed token binds schema version, request/letter kind, record ID, actor ID, database alias and HMAC-SHA256 of current stored record fields (plus linked physical instance fields for letters, response count for requests). No raw body/prompt/address/physical code embedded in token; signing is NOT encryption and metadata including actor/domain ID/alias can be decoded. Tokens are private form state, not public cards or authorization credentials. Do not log or share them. They expire after 1800 seconds; secret rotation invalidates state checks and requires reload.

save_request_draft/save_letter_draft require expected_token. They recheck actor/ownership and compare signed expected state to locked current state, then invoke existing guarded editors and return a fresh allowlisted envelope in the same transaction. Missing/invalid/expired/wrong-scope/differing-state token rejects without saves. A token never bypasses physical/history/publication/restriction guards. Mirror failures roll back both body updates. Reload after DraftConflict; do not silently retry using a freshly fetched token, which would defeat lost-update detection. Future boundaries must handle conflict generically and preserve the user's unsaved text locally without logging it.

This is optimistic STATE comparison, NOT a monotonic revision counter or durable edit ledger. Exact restoration of every fingerprinted value makes an unexpired original token usable again (ABA); no-op saves need not invalidate it. Parent/profile changes outside stored snapshots are not a universal conflict signal; history is checked by existing guards, not all fingerprinted. Both are explicit limits, tested/documented. If every intervening edit must be detected, add a DB-backed revision field and migration in a separate reviewed batch. Lower-level domain_drafts editors still lack token requirements: eventual routes must call domain_editing save wrappers, never bypass them.

Locks serialize cooperating writers on supported databases. SQLite may surface busy/locked errors, and noncooperating admin/courier writes or new inserts are not universally protected. Do not infer HTTP/multiworker/concurrent-revocation safety from sequential two-tab tests. Need deployment-backend concurrency validation before wiring. Tokens are not CSRF protection or creation idempotency keys.

## Existing staged contracts and boundaries
Presentation request cards exactly id/prompt/recipient_alias; letter cards id/body_text/recipient_alias. Audience-filter before projection; lists default20/max100 stable created_at/pk order, no unfiltered counts. Draft card access explicitly owner/writer with approval; no parent/profile/address/history permission. No raw models/relations, account attribution/emails, destination fields, tracking codes, stamps/media/notes/journeys/receipt data in cards. Even approved cards omit addresses. Text allowlisting is not PII scanning or HTML sanitization: use autoescaping/safe Markdown, never raw HTML/mark_safe; review actual text before publication.

Audience unpublished/unknown visibility fails closed; parent bounds body; standalone letter own audience. Approved users may read published restricted content per existing pure policy. Staff/superuser/owner/writer/email/source never substitute for approval. Address requires approval AND readable content, not workspace ownership. Lower-level full querysets/models remain internal, not public response payloads. Viewer approval is captured when queryset constructed; evaluate in a short request, not across caches/revocation; same explicit DB alias. Preserve legacy physical is_public guards separately.

Creation: active approved actor reread from DB; request owner/submitted_by means submitter, not identity ownership of selected Person. Active recipient/place snapshots; missing destinations/on-behalf selection policy still unfinished. Response requires published/readable/open request, snapshots stored parent, creates Letter+hidden physical instance atomically, actor writer, parent remains open. No inferred physical legacy concept. New records unpublished/review_required restricted; public preference is not publication permission. Physical drafts hidden/status=created/origin=online/needs_printing/no stamps. No scanner, publication/restriction-release, finalization or general legacy synchronization.

Draft editing preserves snapshots/codes/attribution/restrictions. Request prompt/audience only for unpublished review_required owner with no legacy source or responses. Letter body/audience only for unpublished/unfinalized review_required writer and exactly one hidden unprinted online created instance with no legacy concept/body mismatch/stamp/hop/media/reputation history. Staged body mirrored atomically; produced copies/reviewed backfills are not rewritten.

Creation replay wrappers domain_submissions require fresh UUID4 per intentional submission, same key/exact input for retry; low-level domain_writes remains non-idempotent. Actor/operation/key-digest unique receipt and HMAC payload; None preference sentinel independent of changing defaults. Mismatch rejects. Actor/ownership rechecked on replay; returns same IDs/current objects, not immutable HTTP response. Missing results retained as null-FK tombstones; incomplete receipts reject; parent closing/unpublishing doesn't create new work on replay. Request returns (request,replayed), response (letter,instance,replayed). Receipt/result/completion atomic, actor locks where supported, DB uniqueness. No autoexpiry; account deletion cascades receipts; deletion/reversal/restore/account removal invalidates guarantees. SECRET_KEY rotation causes fingerprint mismatch; settle rotation/retention/retry policy before rollout. Don't log keys/payload/digests. SQLite busy/locked errors need generic handling and same-input/key retries, never fresh keys after uncertain outcome.

All helpers unwired; live legacy behavior unchanged/authoritative. Existing backfilled content stays unpublished. Initial backfill is provenance, NOT ongoing synchronization. Branch is not yet end-to-end participant-private or production-ready.

## Validate current batch
Preserve unrelated local changes, then:
```
git pull --ff-only &&
git log -1 --oneline &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_editing letters.test_domain_drafts letters.test_domain_presentation letters.test_staged_http letters.test_domain_review &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
No new migrations/saved-data changes expected. Existing user-local 0011 stays applied and counts stay four requests/two letters/two links/no publication/zero planned work. Other environments may lack reviewed schema; don't blindly migrate/backfill/reset/fake. Tests cover sequential two-tab conflicts, token scope/tamper/expiry, ownership/revocation, changed snapshots/physical state, lifecycle guards, atomic rollback, allowlists and ABA limitation. No claim of deployed concurrency from these tests.

## Next work and agent handoff
User prefers direct next bounded preparation on successful run; exact external writes still require approval. Start agents from latest reviewed production-readiness descendant of c64b2c6, coordinate file ownership, preserve unrelated work, report commits/files/tests/skips/DB operations/route changes/risks. Never label planned tests passed. No main merge/deploy/schema/backfill action without separate approval. Update this checkpoint when actual results arrive.

1. Validate state checks; decide if DB monotonic revisions are required, and validate deployment backend concurrency/replay rotation/retention/error semantics.
2. Settle recipient/on-behalf authority, incomplete destinations, review/publication/restriction release, finalization and address/print/courier projections.
3. Inventory all queue/claim/confirmation, browse/desk/detail, print/envelope, scan GET/POST, carry, API, admin, template/serializer, media URL/storage and cache outputs/writes. Keep search/filter/count audience-consistent; test HTTP methods and side effects.
4. Define source-of-truth/synchronization before a separately reviewed coordinated route cutover. Never auto-publish old content or overwrite reviewed targets to make counts match.

Related audit/backfill runbooks have historical status wording; latest checkpoint supersedes status only, not operational cautions. Actual contracts: letters/domain_access.py, domain_writes.py, domain_drafts.py, domain_submissions.py, domain_presentation.py, domain_editing.py.
