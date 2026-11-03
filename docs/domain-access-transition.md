# Domain workflow transition and child-agent handoff

## Last successful checkpoint: user-local, 2026-11-02
Repo Enigma-Infrastructure/deadletter_mailproject; branch production-readiness. Replay code 4b64344 plus restored origin help text passed 38 targeted tests (37 passed/1 skipped) and 159 total tests (158 passed/1 skipped). Checks passed, no model drift; only intended letters.0011 was pending. Metadata fix is committed/pushed as b87dedf42edd3387b1a347bf73e3a548fad9d8cc (GitHub verified). User then applied letters.0011_domain_submission_receipt successfully; no pending operations remain. Assistant did not independently run tests or apply schema. Concurrency test skipped without select_for_update support; deployment-backend multiworker readiness NOT established.

Post-apply user-local audit: four requests/all mapped to four legacy concepts, two authored letters/two linked physical instances, no body differences or missing alias/destination snapshots, no new records published, both instances still need printing. Backfill preview zero work. These are not deployment/child-agent DB evidence. Backup verification was requested but not evidenced by terminal output. Do not rerun backfill --apply or fake/reset migrations. Earlier creation and draft batches passed 133 and 147 total tests respectively.

## Current batch: field-allowlisted presentation, NOT yet validated
Adds letters.domain_presentation and tests. No models/migrations/routes/templates/serializers/admin behavior or saved data changed by commit. New tests NOT executed or reported passing yet. Live legacy routes remain authoritative and unchanged; none of the staged helpers are wired automatically.

Audience request cards contain exactly id/prompt/recipient_alias; letter cards exactly id/body_text/recipient_alias. Helpers filter through persisted domain audience querysets before selecting those fields. Lists evaluate immediately, default 20/max 100, stable created_at/pk descending ordering, no unfiltered counts. Invalid/missing/inaccessible detail IDs return None. No HTTP error mapping, cursor pagination, search/filter APIs or cache implementation in this batch.

Draft cards are separate explicit helpers using owner/writer workspace authorization, not an audience bypass. They do not include parent request IDs/prompts, prompt_snapshot, profiles, addresses, account attribution, emails, location fields, privacy/review metadata, tracking codes, physical instance IDs, stamps, media, notes, journeys or replay receipts. Even approved cards omit addresses; specialized address output remains unimplemented. Request/letter IDs identify already-authorized domain records only. Dictionaries contain scalar fields, not live ORM objects or callable relation traversal. Do not merge raw model dictionaries into them.

Field allowlisting is NOT HTML sanitization, content scanning or a guarantee text is free of personal data: authorized prompt/body/alias may themselves contain sensitive text. Future templates require autoescaping and existing safe Markdown handling; never mark these strings safe or insert raw HTML. Publication/restriction review must address content. Workspace permission does not grant access to related parent/profile/history/address records. Physical hidden guards must remain at future physical boundaries; presentation helpers operate on domain records, not courier/print authorization.

## Existing creation, draft and replay contracts
Persisted active approved server-authenticated actor required for writes/workspace. Staff/superuser/owner/writer/email verification/registration source do not substitute for approval. Request owner/submitted_by means submitter, not ownership of selected Person identity. Active recipient/place snapshots; incomplete destination and on-behalf selection UX remain policy work. Response requires published/readable/open request; snapshots saved request, creates letter/hidden physical instance atomically, credits writer, leaves request open. No inferred physical legacy concept.

New content unpublished/automatically_restricted review_required; public preference is not publication permission. Physical drafts hidden/status=created/origin=online/needs_printing=True/no stamps. No scanner, publication/restriction-release service, finalization or general legacy synchronization. Do not flip flags to print/expose drafts. Full model returns from lower-level services remain internal; use explicit projections at eventual boundaries.

Workspace unpublished requests require owner, letters require writer plus active approval. Finalized unpublished letters can appear but not edit. Request prompt/audience edits require unpublished review_required owner, no historical source or responses. Letter body/audience edits require unpublished/unfinalized review_required writer, one hidden online unprinted status=created instance without legacy concept/body divergence or stamp/hop/media/reputation history. Atomic staged body mirror preserves codes/snapshots/privacy. No edit version token; concurrent legitimate edits can be last-writer-wins. Noncooperating admin/courier writes are not universally locked.

Creation routes MUST eventually call submit_request/submit_response rather than non-idempotent low-level domain_writes. Fresh random UUID4 per intentional submission, SAME key/exact input for transport retry. Unique receipt scope actor/operation/SHA256 key digest; HMAC-SHA256 canonical versioned input fingerprint stores no raw key/prompt/body. None audience is submitted sentinel independent of later defaults. Changed input rejects. Actor approval/target ownership rechecked on replay; returns same IDs/current objects, not immutable HTTP response. Deleted results retain null-FK tombstones and reject recreation; incomplete receipts fail closed. Request wrapper returns (request, replayed); response (letter, instance, replayed). Parent closing/unpublishing does not create new work on replay; prior result returned privately to writer.

Receipt reservation/result creation/completion atomic; actor row lock where supported plus DB uniqueness. No autoexpiry/cleanup; retain account lifetime. Account deletion cascades receipts. Deleting receipts, reversing schema, restoring old DBs or deleting accounts invalidates replay guarantees. SECRET_KEY rotation causes old payload mismatch/fail closed; review rotation policy. Do not log keys/payloads/digests. Hashes are not anonymization. Backend lock/serialization errors propagate; future public boundaries need generic handling and retries only with same key/input. SQLite may return busy/locked. Conditional concurrency test must run on deployment backend before multiworker claims. No route replay integration yet.

## Read policy and validation caveats
Audience unknown visibility/unpublished fails closed; approved users can read published restricted content under current pure policy; parent bounds body; standalone body uses own audience. Address requires approval plus readability, not mere workspace ownership. Full querysets from domain_access/domain_drafts are not redacted output. Approval captured at queryset construction; evaluate within one short request, not across caches/revocation. Same explicit DB alias for viewer/content. No universal concurrent-revocation guarantee. Legacy is_public guards remain separate and must not be weakened.

## Validate this presentation batch
Preserve unrelated local git changes, then:
```
git pull --ff-only &&
git log -1 --oneline &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_presentation letters.test_domain_access letters.test_domain_drafts &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
No new migrations or DB writes expected. User's applied 0011 should remain applied; another environment may still need its reviewed backup/schema application. Do not blindly migrate/deploy/backfill. Unchanged user-local data stays four requests/two letters/two links/no publication/zero planned work. Tests cover exact field sets, omission sentinels, parent gates, publication/restriction, draft ownership/revocation, bounded authorized lists, readonly behavior and explicit lack of HTML/text sanitization.

## Next steps and delegation
User prefers immediate next bounded preparation after a successful run without redundant planning questions. Exact external writes still need approval. Record actual test results/skips and DB operations, never label plans passed. Child agents start from current reviewed production-readiness descendant of b87dedf; coordinate file ownership and preserve unrelated user changes. No main merge/deploy/backfill/schema operations without separate approval.

1. Validate this layer, then implement optimistic draft edit conflict handling; creation replay does not protect stale edits. Test deployment DB concurrency and settle replay retry/retention/secret rotation.
2. Define recipient/on-behalf authority, incomplete destination policy, content review/publication/restriction release, finalization and specialized address/print/courier projections.
3. Inventory every queue/claim/confirmation, browse/desk/detail, envelope/print, scan GET/POST, carry, API, serializers/templates, admin, media URL/storage and cache path. Keep search/filter/count audience-consistent and test HTTP methods/side effects before wiring.
4. Define source-of-truth/synchronization for legacy writes without overwriting reviewed targets. Historical backfill is provenance, not synchronization. Then separately reviewed coordinated route cutover; existing backfilled content is unpublished. Branch is not yet end-to-end participant-private or production-ready.

Related audit/backfill runbooks contain historical pre-validation status wording; current checkpoint supersedes status only, not operational cautions. Implemented contracts: letters/domain_access.py, domain_writes.py, domain_drafts.py, domain_submissions.py, domain_presentation.py. Update this handoff each checkpoint.
