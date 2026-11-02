# Participant roadmap and session handoff

## Baseline
Repository: Enigma-Infrastructure/deadletter_mailproject. Branch: production-readiness only. Baseline commit: cf8b69c38d34a2dc02550387fad18609d5682d32. Inspect actual HEAD and AGENTS.md before continuing.

At the baseline, the user reported successful local checks: no system issues, no model changes, no pending migrations, 13 Batch B tests passed, and 63 full-suite tests passed. These results do not validate later commits.

## Corrected sequence
- B2: integrate existing registration/status/preferences screens into navigation, login, homepage, and permission-aware admin hub; test discoverability and CSRF-protected POST logout. Code supplied by this batch; tests and browser validation NOT yet run.
- A2: finish missing request/body requested visibility, nullable request ownership, separate restriction state/reasons, and request-specific claim digest/expiry/redemption storage. Inspect Person/LetterConcept/LetterInstance mapping before choosing fields. Additive schema and historical backfill must be separate migrations. Existing content becomes Participants only; preserve hidden flags, attribution, credentials, and anonymous unowned history. No route changes yet.
- C: apply defaults to new forms and enforce centralized visibility on queues, prompts, lists, letters, confirmations, carry/location searches, stamps/history, print views, JSON/APIs, and authorized media delivery. Public bodies cannot expose social addresses or broaden restricted requests. Test direct URLs and revoked approval in existing sessions.
- D: authenticated request ownership, private anonymous submission-time-only credentials, secure pending-claim preservation across registration/login, atomic single-use redemption, expiry and concurrency tests. Source codes and public tracking IDs never prove ownership. Defer email recovery.
- E: narrow server-side sensitive-content detection on prompts/bodies/notes, preserve text and requested choice, restrict on edits, permission-controlled review/override, no external AI transmission or unnecessary private-text logging.
- F: shared account-aware rate limiting for registration/login, claims, submissions, reading/search/API, uploads, and scans; document thresholds, proxy/key assumptions, and failure behavior.
- G: integrated suite and browser matrix, migration rehearsal on backed-up copy, backup/restore, protected storage/proxy verification, production checks, separately approved merge and deployment.

## Invariants
Public prompt/permitted alias only. Social/delivery data requires approved participation; recipient email is organizer-only. Body audience cannot broaden request audience. Requested visibility is separate from restrictions. Organizer-hidden content stays hidden from ordinary participants. Pending/rejected/suspended/inactive accounts lack participant access. Approval is separate from staff and ownership. Request owners cannot edit another writer's body or override writer privacy. Source codes are attribution only. Never match historical ownership by alias/email. Claim secrets are request-specific, private, expiring, single-use, digest-stored, and not recoverable from public URLs. No friends/groups/list audiences.

## Child session instructions
Read AGENTS.md and docs/participant-privacy.md, account-schema-validation.md, registration-validation.md, and this document. Historical slice documents describe earlier states; reconcile them with current code. Verify branch, HEAD, and working-tree changes before editing. Local environment is Conda DeadletterMail on Windows/Git Bash. Start with git status --short, git branch --show-current, and git log -1 --oneline. Pull with --ff-only only when safe; never discard unrelated local work.

For every batch: propose exact files/migrations before writing, obtain required approval for exact connector writes, commit only production-readiness, run targeted tests and full suite plus applicable migration checks, and record actual commands/results. If execution is unavailable, say not run. Verify browser journeys from normal navigation, not just direct URLs. Report implemented, tested locally, browser validated, and deployment validated separately. Never infer test success from committed test files.

No main merge, EC2 deployment, database reset, dependency upgrade, or history rewrite without separate authorization. Back up the saved database outside the repository before migration operations; Git rollback is not database rollback. Do not commit database changes or backups.

## B2 validation pending
Run:
```
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test accounts.test_navigation accounts.test_registration accounts.test_participant_review accounts.test_preferences
python manage.py test
```
No migration is expected. Browser-check homepage -> Register -> pending account; login-page registration link; status/preferences links for all signed-in states; admin/source links with and without permissions; logout button; existing Request/Read/Desk/Carry/Scan links. Confirm responsive layout. Use separate organizer/participant sessions for approve/reject/suspend changes. Existing letter routes remain unchanged; privacy warnings must not imply completed enforcement. Only proceed to A2 after this checkpoint is reviewed.
