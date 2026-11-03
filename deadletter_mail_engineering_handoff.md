# Deadletter Mail — Engineering Handoff

Prepared: November 2, 2026, approximately 11:17 PM EST.

This document consolidates the implementation history, user-reported validation, local database checkpoints, constraints, and next work from the parent-agent conversation. It is intended to stand alone for a child agent or another engineer.

## 1. Executive summary

The project is partway through a staged Django domain/privacy transition on `production-readiness` in `Enigma-Infrastructure/deadletter_mailproject`.

Implemented and locally tested components include:

- Separate recipient-specific `LetterRequest`, authored-work `Letter`, and physical-copy `LetterInstance` concepts.
- Aggregate-only source audit and explicit historical backfill commands.
- Persisted participant audience checks.
- Transactional creation services with conservative publication defaults.
- Owner/writer draft workspaces and guarded edits.
- Durable creation replay receipts.
- Field-allowlisted presentation helpers.
- Signed draft-state tokens and token-checked save wrappers.

These are staged components. They have NOT been connected to a coordinated replacement for the live legacy workflows. Existing website routes remain authoritative. This is NOT a completed participant-private application, production deployment, publication workflow, ownership-claim system, or general synchronization system.

The latest source checkpoint is `dfc28bf` (staged HTTP integration harness). Its targeted suite (domain editing + drafts + presentation + staged HTTP) passed all 64 tests. The full suite ran 209 tests; 193 passed, 15 errored (all sandbox `PermissionError` on temp-file/subprocess operations, not code regressions), and 1 skipped. System checks passed, no model drift was detected, and no pending migration operations were reported.

The isolated HTTP integration harness for the staged presentation and token-checked editing services is now implemented and committed. It is NOT wired to the live project URL configuration.

## 2. Evidence and access limitations

### Evidence provenance

- Test, audit, migration, and browser results below were pasted by the user from their local environment.
- The parent assistant did not independently run Django tests or operate the user's database.
- Earlier commits and source files were read and written through the GitHub connector, with explicit approval for each exact external write.
- The latest source commit shown in the user's local terminal is not proof of the current remote head if subsequent work occurs.
- No production deployment commit, hosted-site URL, deployment health check, or production database checkpoint was established.
- Database backup verification was requested before writes, but the pasted terminal output does NOT demonstrate that a backup was made or verified.

### Current GitHub connector blocker

The final attempted GitHub reads returned:

> This connector requires a Perplexity Pro or Max subscription (or, for eligible connectors, available free-turn access), which this account doesn't have.

Those reads were denied. No next-pass code was created or committed afterward. The user requested this handoff instead.

Do not claim to have current repository access or to have committed changes without a successful tool result. Restore eligible connector access, or work in an authorized local checkout with the actual files supplied. Never pretend a proposed patch is already in GitHub.

## 3. Repository and environment

- Repository: `Enigma-Infrastructure/deadletter_mailproject`
- Working branch: `production-readiness`
- User environment: Windows, Git Bash / MINGW64, virtual environment shown as `(DeadletterMail)`.
- Local checkout shown under `~/Documents/Code Bases/deadletter_mailproject`.
- User's development-server output reported Django `6.1.1` and settings `deadletter_mailproject.settings`.
- The browser smoke check used the local development server at `http://127.0.0.1:8000/`.
- This does not establish the database backend or the configuration of a deployment environment. The concurrency test skip is consistent with missing `select_for_update` support; do not infer a backend solely from the skip.

Before work, inspect the checkout and preserve unrelated changes:

```bash
git status --short
git branch --show-current
git log -5 --oneline
```

Do not blindly reset to a baseline SHA. Coordinate branch/file ownership with other agents.

## 4. Commit chronology and checkpoints

| Commit | Purpose / significance |
|---|---|
| `398b9a9` | Last identified direct active intake/account UI change: remove public-intake email collection and add account prompts. November 2, approximately 12:16 PM EST. |
| `56b7dfa` | Add request/authored-letter foundation without intended workflow changes; migration `0010`. |
| `35828b9` | Restore existing stamp delivery label, `Delivered it`. |
| `b5a450e` | Read-only aggregate source audit. User reported 101 total tests passing. |
| `88ec035` | Preview-first historical backfill. User reported 112 total tests passing; later applied local conversion. |
| `71a7f2f` | Persisted domain access adapters. User reported 121 total tests passing. |
| `f4bcb2b` | Staged transactional creation services and handoff refresh. User reported 133 total tests passing. |
| `348c49f` | Guarded draft workspace/edit services. User reported 147 total tests passing. |
| `4b64344` | Durable submission replay receipts/wrappers and migration `0011`. Introduced accidental origin metadata drift, fixed separately. |
| `b87dedf` | Restore `LetterInstance.origin` help text. Parent verified the pushed GitHub correction. Replay baseline then had 159 tests, 158 passing / one skipped. |
| `c64b2c6` | Field-allowlisted presentation helpers. User reported 168 tests, 167 passing / one skipped. |
| `120e540` | Signed draft-state snapshots and token-checked saves. Latest user report: 177 tests, 176 passing / one skipped. |
| `dfc28bf` | Isolated staged HTTP integration harness (adapters, URLconf, 32 tests). Targeted 64/64 pass; full 209 with 15 sandbox errors / 1 skip. |

Latest full SHA:

```text
dfc28bf
```

Previous checkpoint:

```text
120e54065aeecbd0ab670e7d04032c828d50c762
```

Metadata correction full SHA:

```text
b87dedf42edd3387b1a347bf73e3a548fad9d8cc
```

## 5. Latest validation and the post-browser uncertainty

### Latest completed validation

The user ran:

```bash
git pull --ff-only &&
git log -1 --oneline &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_editing letters.test_domain_drafts letters.test_domain_presentation &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```

Observed results at `120e540`:

- System checks: no issues.
- Model consistency: `No changes detected`.
- Migration plan: no planned operations.
- Targeted suite: all 32 passed.
- Full suite: `Ran 177 tests`, `OK (skipped=1)`.
- The known conditional replay concurrency test is skipped on backends without `select_for_update` support. Deployment-backend concurrent behavior remains unverified.

### Database audit immediately before browser activity

| Category | Observed local state |
|---|---|
| Legacy concepts | 4; all have recipients, destinations, and nonempty prompts |
| Legacy-to-request mappings | 4 |
| Concepts with no instances | 2 |
| Concepts with one instance | 2 |
| Recipient conflicts / missing instance concept or recipient | 0 |
| New requests | 4; all open; no owner or submitter assigned |
| Authored letters | 2; both have requests and instances; no writers assigned |
| Missing alias/destination-label snapshots | 0 |
| Linked legacy/authored body differences | 0 |
| Physical instances | 2; both linked; both have nonempty bodies |
| Printing | Both need printing; neither has printed timestamp |
| Legacy `is_public` | True for both |
| New publication / requested public | 0 requests and 0 letters |
| Finalized authored letters | 0 |
| Stamps, stamp updates, hops, media, reputation events | All 0 |
| Backfill preview | Zero requests/letters/links planned |

### Important: browser activity happened AFTER that audit

The later development-server log includes:

```text
POST /write/request/ HTTP/1.1 200
```

A 200 does not establish whether submission succeeded or the form returned validation errors. If successful, the still-legacy intake may have created an additional concept without a new-domain request mapping.

The parent requested these read-only checks, but no subsequent output is present in this handoff:

```bash
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```

Do not assume the saved database still has exactly four requests/four concepts after the browser POST. Do not apply the backfill automatically or force counts back to an earlier checkpoint. Legitimate new source records are not necessarily regressions.

## 6. Browser smoke-test evidence

User ran the local development server successfully. Logs show:

- `/admin/` redirected to login, login page returned 200.
- Admin login POST redirected, then `/admin/` returned 200.
- `/`, `/write/request/`, `/letters/read/`, `/letters/desk/`, `/scan/`, `/leaderboard/`, `/accounts/status/`, and `/accounts/preferences/` returned 200.
- The request form had a POST returning 200, with result semantics unknown as noted above.

The log also printed `Session data corrupted` before successful admin login. No cause was diagnosed. Do not attribute it to secret rotation, data loss, or a specific commit without investigating. Successful login followed, but that alone does not prove all session behavior is healthy.

This is local HTTP smoke evidence, not screenshots, visual-layout verification, full workflow validation, or hosted-site evidence. The user did not explicitly confirm desktop/mobile appearance, print completion, scan update submission, or all account-contact interactions.

## 7. Domain model split

### `LetterConcept`

Legacy mixed-purpose concept/request row, retained during transition. Includes prompt, recipient (`created_for`), destination and legacy creator metadata. A recipient-specific source is not automatically reusable inspiration.

### `LetterRequest`

Recipient-specific invitation, with:

- `prompt`, recipient and alias/destination snapshots.
- Optional reusable `concept` link.
- Unique `legacy_source` provenance link to a legacy concept.
- Separate `owner` and `submitted_by` account fields.
- Requested audience, automatic restriction/reason, publication and open flags.

Provenance is not ownership. Legacy `created_by`, matching aliases, email addresses, registration, or login do not prove ownership.

### `Letter`

Authored work, distinct from its physical copies. Includes request/concept, writer, body, prompt/recipient/destination snapshots, requested audience, restriction/publication, and finalization state.

### `LetterInstance`

Physical copy, preserving legacy content and workflows during cutover. Has `authored_letter` link, legacy concept/recipient/body, unique code, current location, status, origin, printing state, legacy public flag and creator.

Do not replace instances or regenerate codes during conversion. Physical journey/reputation/media records remain tied to the instance.

### `DomainSubmissionReceipt`

Private replay metadata added by schema-only migration `0011`:

- Actor, operation, key digest, payload digest, completion flag.
- Nullable result links to request, letter, instance.
- Created timestamp.
- Unique actor/operation/key-digest constraint and known-operation constraint.

No raw submission key, prompt or body is stored in the receipt. Receipt contents still are not public or automatically anonymous.

## 8. Implemented modules and contracts

### A. Pure policy — `letters/access_policy.py`

Defines `Viewer`, `ContentAccess`, participation/audience enums and request/body/address decisions.

- Active authenticated approved participation is separate from staff, superuser, ownership, authorship, email verification and registration source.
- Unknown audience and unpublished content fail closed for audience reads.
- Published body cannot broaden its originating request's audience.
- Approved participants may read published restricted content under the current policy.
- Social-address access requires approval plus appropriate readable content.

### B. Persisted audience adapters — `letters/domain_access.py`

Rereads account approval/active state from the selected database. Supplies readable querysets, saved-record audience checks and address checks.

Querysets contain full models, not redacted public payloads. Approval is captured at queryset construction; do not cache/reuse across requests or approval changes. No universal concurrent-revocation guarantee is established.

Domain audience checks do not replace legacy physical `is_public` guards or independently grant printing, courier, editing or admin permissions.

### C. Creation — `letters/domain_writes.py`

Low-level staged creation services, deliberately non-idempotent:

- `create_request`: approved actor; active recipient and recorded place; snapshots alias/place/city; owner/submitter are actor, not proof of identity ownership of Person.
- Missing place can yield incomplete/city-only destination for later review. Recipient-selection/on-behalf UX remains unresolved.
- `create_response`: approved actor; published/readable/open parent; snapshots saved request; creates authored letter and physical instance atomically; writer is actor; parent remains open.
- No client-controlled attribution/publication/restriction authority parameters.
- New content stays unpublished and automatically restricted with `review_required`.
- New physical draft is hidden, `status='created'`, `origin='online'`, needs printing, no printed timestamp or stamp.
- Body is mirrored once into the legacy instance field for staging. This is not general continuing synchronization.

### D. Draft ownership/edit guards — `letters/domain_drafts.py`

- Unpublished request workspace: explicit approved owner.
- Unpublished letter workspace: explicit approved writer.
- No staff/submitter/parent-owner bypass.
- Finalized unpublished letters may appear in workspace but cannot be edited through these services.
- Request edit: prompt/requested audience only, unpublished `review_required` restricted state, no historical source or responses.
- Letter edit: body/requested audience only; unpublished/unfinalized review draft; exactly one hidden unprinted online created instance; no legacy concept, body divergence, stamp, hop, media or reputation history.
- Atomic body mirror preserves codes, snapshots, attribution, timestamps and restrictions.
- Produced copies and reviewed backfilled targets are not silently rewritten.

These lower-level editors do NOT require signed expected-state tokens. Future routes must use the checked wrappers described below, not bypass them.

### E. Durable creation replay — `letters/domain_submissions.py`

- `submit_request` returns `(request, replayed)`.
- `submit_response` returns `(letter, instance, replayed)`.
- Fresh UUID4 per intentional submission; SAME key and exact input for transport retries.
- Scope: actor + operation + SHA256 key digest.
- Versioned canonical HMAC-SHA256 input fingerprint; submitted `None` audience is distinct from explicit preference and independent of later account-default changes.
- Reservation, result creation and completion share one transaction.
- Identical replay returns same IDs/current objects, not an immutable historical HTTP response.
- Changed input under same key rejects without overwrite.
- Approval and result owner/writer are rechecked on replay.
- Parent closing/unpublishing does not create new work on replay; prior result returns privately to its writer.
- Missing result retains null-FK tombstone and rejects recreation; incomplete persisted receipts fail closed.
- No automatic expiry/cleanup; account deletion cascades receipts.
- Receipt deletion, account removal, schema reversal or old backup restoration can invalidate replay guarantees.
- SECRET_KEY rotation causes old payload fingerprints to mismatch; operational rotation policy remains unfinished.
- Do not log raw keys, payloads or digests. Do not retry ambiguous outcomes with a fresh key.
- Database lock/serialization errors propagate; future HTTP boundaries need generic handling. SQLite may return busy/locked. Deployment-backend concurrency validation remains required.

Future creation routes must use these wrappers, not raw `create_request` / `create_response`.

### F. Field allowlists — `letters/domain_presentation.py`

- Request card: exactly `id`, `prompt`, `recipient_alias`.
- Letter card: exactly `id`, `body_text`, `recipient_alias`.
- Audience filters apply before projection.
- Lists evaluate immediately, default 20 / max 100, deterministic created-at / primary-key descending ordering.
- Invalid/missing/inaccessible detail IDs return `None`.
- Private draft cards are separate owner/writer helpers, not an audience bypass.
- No parent IDs/prompt snapshots, raw relations, account attribution, emails, addresses/location snapshots, tracking codes, instance IDs, stamps/media/history or receipts.
- Even approved cards omit addresses; specialized address output is not implemented.

Allowlisting is NOT HTML sanitization or PII scanning. Permitted prompt/body/alias text can itself contain sensitive or unsafe text. Future rendering must retain appropriate escaping/safe Markdown behavior and must not blindly mark content safe.

### G. Signed expected state — `letters/domain_editing.py`

- `request_draft_snapshot` / `letter_draft_snapshot`: private `{card, edit_token}` envelope for approved owner/writer and unpublished target.
- Signed token binds version, kind, record ID, actor ID, database alias, and HMAC of stored state.
- Includes stored record fields; letter state also includes linked instance fields; request state includes response count.
- Token expires after 1,800 seconds.
- Token contains no raw body/prompt/address/code, but signing is not encryption: its scope metadata can be decoded. Do not log/share it.
- `save_request_draft` / `save_letter_draft` require `expected_token`.
- Recheck authorization, compare expected/current state under cooperating row locks, invoke existing edit guards, return refreshed envelope in one transaction.
- Invalid/stale/expired/wrong-scope state raises `DraftConflict` without saves.
- Token never bypasses lifecycle/history/restriction guards.
- Snapshot availability does not promise editability.
- After conflict, reload; do not secretly fetch a fresh token and auto-save stale client text.
- Tokens are neither CSRF protection nor creation replay keys.

Important limitation: this compares STATE, not monotonic revision history. Exact restoration of all fingerprinted values permits the old unexpired token again (ABA); no-op saves may not invalidate it. Parent/profile changes outside stored snapshots are not universal conflict signals. If every intervening edit must be detected, a separate DB-backed revision design/migration is needed. Sequential two-tab tests do not establish multiworker HTTP safety.

## 9. Audit and backfill operations

### Read-only inventory

```bash
python manage.py audit_letter_sources --json
```

Reports aggregate counts only; no raw content, aliases, email addresses, codes or record IDs. Aggregates can still reveal activity; share deliberately.

### Historical conversion

```bash
python manage.py backfill_letter_sources
```

Defaults to read-only preview. `--apply` is an explicit database write and is NOT currently needed to reproduce the completed local checkpoint.

Backfill behavior:

- One request per eligible legacy concept with recipient, including unanswered sources.
- Recipient-less concepts remain unclassified; their instances and orphans can become standalone letters.
- One authored letter per unlinked instance; no body-text deduplication.
- Reject pending instance recipient missing/conflicting relative to recipient-specific concept.
- Preserve source provenance, exact text, creation times, codes, print/journey/history records.
- No inferred ownership/writer attribution or reusable-concept links.
- Existing mappings/links and edited targets preserved, not repaired or synchronized.
- Hidden legacy instance creates `legacy_hidden` restriction on new authored record.
- New records remain unpublished/participants-only during historical conversion.

Stop writers and use a verified database backup before any separately approved database conversion. Never reset the database or fake migration history to pass a check.

## 10. Known defect and correction to preserve

Replay commit `4b64344` accidentally removed this existing field metadata:

```python
help_text="Where this letter was created.",
```

from `LetterInstance.origin`. The user observed a proposed `0012_alter_letterinstance_origin.py` during `makemigrations --check --dry-run`.

The source metadata was restored locally, tests rerun, and correction committed/pushed as `b87dedf`. No compensating `0012` was needed. Preserve the restored line. The dry-run suggestion was not evidence that an `0012` file had been created.

The only new schema intended by the replay batch was `0011_domain_submission_receipt`, which is now user-applied locally.

## 11. Staged HTTP integration harness — implemented at `dfc28bf`

### Objective

Add an isolated HTTP integration harness for existing audience presentation and token-checked draft services, WITHOUT adding it to the live project URL configuration yet.

This moves verification from direct service calls toward actual HTTP semantics without switching the current website or publishing old content.

### Implemented deliverables

- Dedicated staged HTTP adapters and an isolated URL configuration used by tests only.
- GET audience list/detail responses using explicit presentation allowlists.
- Separate approved owner/writer private draft snapshot and save boundaries.
- Token-checked saves through `domain_editing`, not lower-level editors.
- Generic validation/permission/conflict/database error mapping without raw SQL, secrets, content, or exception traces in responses.
- CSRF enforcement, deliberate allowed-method handling and appropriate private/no-store behavior.
- Strict input allowlists: client requests must not control owner/writer/submitter, publication/restriction, physical state, legacy-source mapping or other authority fields.
- Integration tests that check both returned data and absence of unintended writes.
- Update this document / repository transition document with actual new results and limitations.

### Required test cases

1. Anonymous versus approved audience reads, including parent-request bounds.
2. Exact output keys; no addresses, account metadata, tracking codes, raw ORM relations or history.
3. Private owner/writer checks, no staff/submitter bypass, approval revocation.
4. CSRF rejection with no writes, and a valid authorized CSRF-protected save.
5. Wrong HTTP methods with no writes.
6. Missing/invalid/expired/stale expected-token conflicts without overwriting a newer body or its mirror.
7. Unknown/forged authority fields rejected rather than persisted or reflected.
8. Generic database failures without details; atomic rollback maintained.
9. Existing live routes remain unchanged; staged URLconf not included in main routing.

Do not quietly expose creation endpoints before recipient-selection/on-behalf authority, review/publication and related policies are resolved. Do not infer hosted-site readiness from a test-only URL configuration.

### Remaining larger decisions

- Whether signed state comparison suffices or a monotonic DB revision is required.
- Deployment-backend concurrency behavior and retry policy.
- Replay receipt retention and secret-rotation behavior.
- Recipient selection/on-behalf authority and incomplete destinations.
- Content review, publication/restriction release and finalization.
- Specialized address, printing and courier projections/permissions.
- Source of truth and synchronization for ongoing legacy writes.
- Coordinated route/UI cutover with field-level output, search/filter/count consistency.

## 12. Current website / UI boundary

The last identified direct active intake/account UI change was `398b9a9` (November 2, approximately 12:16 PM EST): forms, intake persistence, request template/JavaScript and confirmation account links.

Subsequent work mainly added schema and staged backend components. That is not a guarantee of zero runtime risk; shared models and schema can still affect startup or existing behavior.

Do a short browser check after active views/URLs/templates/JS/auth/privacy changes and after schema/deployment changes. Do not confuse local runserver behavior with a hosted deployment. Prefer read-only hosted checks; production submissions, registrations, print confirmations and scan updates are actual writes.

No active UI integration was performed by the signed-state or allowlist batches. No claim is made that a new edit interface exists.

## 13. Validation commands for the next agent

First establish source and database state. Inspect before pulling; preserve local work.

```bash
git status --short
git branch --show-current
git log -5 --oneline
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py audit_letter_sources --json
python manage.py backfill_letter_sources
```

For baseline regression testing:

```bash
python manage.py test letters.test_domain_editing letters.test_domain_drafts letters.test_domain_presentation letters.test_staged_http
python manage.py test
```

The staged HTTP test module (`letters.test_staged_http`) is now part of the targeted suite. Report full counts and skips. Do not claim a skipped concurrency test passed. Tests run in a separate test database; test success does not prove saved/deployment data matches historical local counts.

No new migration is expected for an HTTP-only batch. If drift appears, inspect the exact difference; do not add a compensating migration without reviewing whether source metadata was accidentally changed.

## 14. Documentation and delegation rules

Primary existing repository document:

```text
docs/domain-access-transition.md
```

At `120e540`, that document records the preceding 168-test checkpoint and labels signed-state tests unvalidated. The user's new successful 177-test run supersedes those status statements, but the repository document has NOT yet been refreshed with that result. This handoff records it; do not claim the repository has already been updated.

Related repository docs:

- `docs/source-audit-validation.md`
- `docs/source-backfill-validation.md`
- `docs/email-contact-validation.md`
- `docs/participant-roadmap.md` and `docs/reputation-backlog.md` were referenced in earlier repository material; inspect before relying on their present contents.

Earlier docs may contain historical pre-validation wording. Update status from actual evidence without deleting operational cautions.

User preference: after a successful run is confirmed, proceed directly to preparing the next bounded batch rather than asking another generic planning question. This is NOT blanket permission for arbitrary writes or deployment.

For external state changes, resolve the exact repository/branch/files, present the complete proposed action, obtain required approval, then execute exactly the approved content. Reconfirm if the content changes. Never silently alter approved source, fabricate commit success, or claim unexecuted tests passed.

Do not merge to main, deploy, apply schema/backfills, clear sessions, erase data, or broadly change publication/approval/ownership without separate explicit scope and approval.

## 15. Handoff acceptance / return report

A child agent should return:

- Starting and resulting commit SHAs and branch.
- Changed files and exact implemented scope.
- Tests actually executed, counts and skips.
- Database operations actually performed (or explicit none).
- Whether main routing, templates, UI, admin or deployment behavior changed.
- Current post-browser audit, not an assumed old count.
- Remaining risks and unresolved policies.
- Updated repository handoff/checkpoint status, if access and approval allowed the update.

### Return report — November 2, 2026, ~11:47 PM EST (this session)

- **Starting commit:** `120e54065aeecbd0ab670e7d04032c828d50c762`
- **Resulting commit:** `dfc28bf` on `production-readiness`
- **Changed files:** `letters/staged_http.py` (new), `letters/staged_urls.py` (new), `letters/test_staged_http.py` (new, 32 tests)
- **Implemented scope:** Isolated HTTP integration harness for domain presentation and token-checked editing. NOT wired to live URL configuration.
- **Tests executed:** Targeted 64/64 pass (domain editing + drafts + presentation + staged HTTP). Full suite 209 tests: 193 pass, 15 error (sandbox `PermissionError` on temp-file/subprocess ops — not code regressions), 1 skip (concurrency).
- **Database operations:** None. No migrations, no backfill, no audit writes.
- **Main routing / templates / UI / admin / deployment:** Unchanged. Staged URLconf is test-only.
- **Post-browser audit:** Not performed this session (no browser activity). The post-browser uncertainty from the prior handoff remains unresolved.
- **Remaining risks:** ABA limitation on signed-state tokens; deployment-backend concurrency unverified; replay receipt retention and secret-rotation policy unfinished; recipient-selection/on-behalf authority unresolved; content review/publication/finalization unresolved; source-of-truth synchronization for legacy writes unresolved.
- **Test fixes applied:** Three test bugs corrected in `test_staged_http.py`: (1) CSRF test used invalid `self.client.login()` context manager — replaced with fresh `Client(enforce_csrf_checks=True)`; (2) live-routes test attempted to hit live URLs under the staged `ROOT_URLCONF` override — changed to verify main URLconf patterns; (3) stale-token test used a fresh token (post-edit) instead of reusing the now-stale original token.

Immediate practical order: obtain post-browser audit/preview; resolve remaining larger decisions (section 11); prepare next bounded batch (coordinated route/UI cutover or content review/publication workflow); keep live cutover separate.
