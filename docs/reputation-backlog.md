# Reputation and leaderboard backlog

## Decision: deferred
Recorded 2026-11-02. Capture these ideas only; do not implement them as the next batch. Account framework work remains the priority. This note does not change scoring, permissions, schemas, or existing behavior.

## Current priority
1. Validate the account/admin layout batch (3343f7d) locally and in the browser.
2. Review and implement the separately approved account-email/intake foundation: optional User.email, email_verified default false, secure account-contact editing and verification invalidation, read-only admin status, removal of new request email collection while preserving legacy Person.email, and truthful post-submission registration/login prompts. No outbound verification or request claiming is implied.
3. Complete A2 content/claim schema, C visibility integration, and D ownership/claim workflows under docs/participant-roadmap.md and docs/account-layout-validation.md.
4. Revisit this backlog once identity, approval, account contact, privacy boundaries, and request ownership are established. Do not postpone essential authorization or replay-abuse fixes discovered along the way just because feature gamification is deferred.

## Ideas to evaluate, not approved implementation requirements
- Explain earning rules and distinguish reports from physical handoffs.
- Define qualifying actions and stop duplicate/replayed reward awards with server-side idempotency, transaction handling, and concurrency tests.
- Keep an auditable event ledger and define correction/reversal handling.
- Consider opt-in public leaderboard participation and a separately permitted display alias instead of automatically publishing login usernames.
- Consider collective progress based on distinct letters helped, not raw scan counts; scope event/city views only after defining membership, attribution, and privacy.
- Recognize intermediate hops without pressuring each carrier to complete a delivery.
- Avoid incentives for unnecessary photos, private-data disclosure, repeated notes, or artificial handoff loops.
- Consider badges/seasonal recognition only after observing actual usage; avoid inactivity penalties and streak pressure initially.
- Explicitly define pending/suspended/anonymous scoring and display behavior; do not silently auto-approve participants or retroactively award anonymous actions by matching identifiers.

## Boundaries
Reputation is appreciation, not verified identity, proof of delivery, ownership, approval, or an authorization credential. Points never grant private-content access or staff privileges. Email verification never proves request ownership or independently grants participant approval. Public aggregates must not reveal protected letter relationships, locations, or activity histories. Existing rules remain unchanged until a separately reviewed patch and migration plan are approved.

## Handoff
Read this alongside docs/participant-roadmap.md and docs/account-layout-validation.md. Do not start a reputation redesign without a new user-approved scope. No deployment, merge to main, or dependency changes are authorized by this note.
