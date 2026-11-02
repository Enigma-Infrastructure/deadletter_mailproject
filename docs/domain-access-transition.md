# Domain workflow transition and child-agent handoff

## Validated baseline (user-local evidence, 2026-11-02)
Repository: Enigma-Infrastructure/deadletter_mailproject. Branch: production-readiness. Last user-validated code commit: 71a7f2f43ab13ca00cccd474bc4591ae07178074. The user reported all 28 targeted tests and all 121 tests passed, no system-check issues, no model drift, and no pending migration operations. The author did not execute these tests independently.

Their local database was backfilled with the command from 88ec035: four LetterRequests, two Letters, and two existing LetterInstances linked. The latest audit retained four legacy concepts, all mapped; zero linked body differences; zero missing alias/destination snapshots; zero new records published; both instances still need printing. Latest preview planned zero requests/letters/links. This is local evidence only, NOT deployment or child-agent database state. Backup verification was requested but is not evidenced by the pasted terminal output. Do not claim it was verified.

## This batch: staged writes, not yet validated
Adds letters.domain_writes plus tests. These new tests have NOT been executed by the author or reported by the user yet. No models, migrations, routes, templates, serializers, admin actions or saved data are changed by this commit. The services are intentionally unwired. A child agent must distinguish this proposed/committed batch from the validated 71a7f2f baseline.

create_request(user, recipient_id, prompt, requested_visibility) requires a server-authenticated active approved actor, rereads account/defaults, and snapshots an active Person's alias and pirate place/city. An inactive recorded place rejects the operation. An absent place permits city-only/incomplete snapshots for later review. owner and submitted_by are the submitting actor, not a claim that actor owns or is the selected Person. No matching by alias/email or legacy created_by. Recipient selection/privacy and on-behalf UX still need route-level design. No legacy concept is created or claimed.

create_response(user, request_id, body_text, requested_visibility) requires active approval and a published, readable, open request; there is no owner/staff unpublished-draft bypass. It creates a new Letter and LetterInstance atomically. Snapshots come from saved request fields, not changed recipient profiles. Existing request concept links are retained on the Letter only; the physical instance has no legacy concept mapping. Attribution is the actor. The request stays open, permitting multiple independent responses.

All new service-created content is unpublished and automatically restricted with review_required; public audience preference is NOT publication permission. No automated personal-data scanner or restriction-release/publication service is supplied here. New physical instances are is_public=False, status=created, origin=online, needs_printing=True with no stamp/printed_at. Body text is mirrored once into the legacy field for staging, not a continuing dual-write guarantee. Existing public guards therefore exclude these staged instances. Do not enable a new print or public route by merely flipping these flags. No finalization or legacy synchronization is performed.

Duplicate semantics: each successful service call is a separate submission, even for identical text. There is no idempotency key or HTTP replay protection; do not wire to routes or auto-retry on an ambiguous outcome before implementing a reviewed replay policy. A failure inside the transaction rolls back the new records; generated-code collision is surfaced rather than retried automatically. No legacy/backfilled target records are overwritten. Service errors and returned full models are internal, not safe public responses.

Transactions use the selected database alias and lock actor/request/recipient/place rows where supported, with no nullable joined locks. This is not universal cross-backend concurrent-revocation protection: SQLite row-lock semantics differ and noncooperating writes still exist. Caller must handle database errors generically, without exposing SQL or content, and must not infer multiworker replay safety from these unit tests.

## Existing read adapters and security boundaries
letters.access_policy contains pure audience rules. letters.domain_access supplies persisted audience filters, not edit/print/courier permissions. It rereads account is_active and participant_status; stale approval, staff/superuser flags, ownership, authorship, email verification and registration source are not participant approval. Anonymous/inactive/unapproved users retain only public unrestricted reads. Approved active participants can read published restricted content under the current pure policy. Unknown audience or unpublished records fail closed even for approved readers. Standalone letters use their own audience; response bodies cannot broaden parent-request audience.

Address gates require approved participation AND readable content. Querysets contain full private models, NOT safe response payloads; do not pass them directly to public templates/serializers. Request/body read permission does not expose destination snapshots, profile/email relations, media, notes, journeys or tracking codes. Legacy is_public guards remain separate and must not be weakened. These adapters are not wired to live views.

A queryset captures approval at construction. Build/evaluate within one short request, not across requests/approval changes or caches. Same explicit alias for viewer/content. This is not a transaction-wide authorization snapshot. Owner/writer draft editing and admin preview remain separate unfinished permission paths.

## Validation for this batch
Check git status and preserve unrelated work before pulling.
```
git pull --ff-only &&
git log -1 --oneline &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_writes letters.test_domain_access letters.test_source_backfill &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
No migrations/data changes expected. Do NOT add --apply for this validation. For unchanged user-local data expect four requests/two letters/two links, no publication and zero planned backfill work. Do not assume those counts on another database. Tests cover attribution, atomic failure, profile-independent snapshots, stale approval/defaults, input rejection, repeated text, hidden staging and existing-record preservation. These are service tests, not HTTP/multiworker concurrency tests.

## Child-agent task boundaries and next work
Start from the latest reviewed production-readiness descendant of 71a7f2f; inspect git status, current files and test evidence rather than blindly reverting to the baseline. Coordinate file ownership before parallel work; no direct main merge/deployment/backfill execution without separate approval. Preserve unrelated user changes. Never infer identities or auto-publish/unrestrict backfilled records.

1. Validate this service batch, then design replay protection and request/draft authorization before route integration. Define recipient selection/on-behalf ownership, review/publication/restriction-release, and finalization explicitly.
2. Inventory every read/output path: writing queue/claim/confirmation, browse/desk/public detail, print/envelope, scan GET/POST, carry list, API, serializers, templates, media storage/URLs, admin and caches. Add field-level presentation objects; search/filter/count output must use the same audience. Preserve physical hidden flags. Decide approved-reader/print/courier behavior independently and test all HTTP methods and side effects.
3. Define source of truth and synchronization for legacy edits/new writes without overwriting reviewed new records. The historical backfill is provenance-preserving initial conversion, not synchronization. Legacy public behavior is still authoritative and unchanged.
4. Only then propose a coordinated, separately reviewed workflow cutover. Switching reads now would hide unpublished backfilled content. This branch is not yet an end-to-end participant-private or production-ready application.

## Related operational documents
- docs/source-audit-validation.md: aggregate-only inventory.
- docs/source-backfill-validation.md: explicit preview/backup/apply procedure and limitations. Its original pre-validation status statements are historical; use the checkpoint above for latest user-local evidence.
- letters/domain_writes.py and letters/domain_access.py: actual implemented contracts.

When handing work back, report commit, changed files, tests actually executed, database operations actually performed, remaining risks and whether routes were touched. Update this document with new evidence; do not upgrade an unexecuted test plan to a passed checkpoint.
