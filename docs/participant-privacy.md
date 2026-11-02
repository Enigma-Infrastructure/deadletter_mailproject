# Participant privacy implementation contract

## Status

This first slice adds pure policy functions and their tests only. They are NOT
yet connected to existing views, APIs, serializers, models, forms, or media
serving. Existing public access has NOT changed. Do not deploy this branch
with a claim that participant-only protection is complete.

The policy matrix test checks 256 combinations of authentication, active
status, approval status, request/body visibility, and independent automated
restrictions. Separate tests check unpublished content and unknown values.
Tests must be run locally; a commit is not evidence they passed.

## Agreed audience rules

- New anonymous requests default to Public in the future form implementation.
- Public requests expose the permitted recipient alias and writing prompt.
- Social addresses, location associations, journey notes, and photos require
  approved-participant access; recipient email remains organizer-only.
- A body has independent Public / Participants-only visibility. A public body
  cannot broaden a participants-only or automatically restricted request.
- A detection restriction narrows the audience without erasing the submitted
  text or the submitter's requested visibility. It is not a safety guarantee.
- Unpublished/organizer-hidden content remains unavailable through ordinary
  participant routes. Staff admin access is checked separately.
- Account approval never grants staff privileges or ownership of aliases.
- Public writer attribution requires a separate explicit choice.
- Unknown future audience values fail closed until implemented.

A Viewer must be built from current server-side authentication, is_active,
and persisted approval status for each request. Do not cache approval in a
long-lived session or accept policy inputs from form fields without validation.
The policy module does not authorize editing, claiming, contact-email access,
or access to journey/media resources; those require explicit adapters/checks.

## Account and request behavior to implement next

- Registration starts pending. Approved, rejected, and suspended are separate
  states; staff review metadata is recorded. Existing admins are preserved.
- Registration selects defaults for new requests and bodies. Later preference
  changes affect future submissions only. New-account defaults start Public.
- Optional source codes support QR query parameters and manual entry. They
  are public attribution, not proof of attendance or automatic approval.
- Authenticated new requests link to their submitter. Anonymous requests can
  later link through a private expiring single-use credential, stored as a
  digest. Public letter identifiers and stamp codes are not claim secrets.
- Anonymous claim secrets are shown only in the submission response, not on
  a revisitable public confirmation page. Account signup preserves the claim
  securely. Redemption is atomic and never bypasses participant approval.
- No automatic ownership matching by alias/email, including historical data.
- Ownership of a request does not grant editing rights over another writer's
  body or permission to broaden that writer's chosen audience.
- Email claim recovery is deferred until verification/mail delivery exists.
- Existing records backfill to Participants only; historical hidden flags stay
  hidden. Ordinary accounts are not silently approved.
- Friends/groups audiences remain unimplemented.

## Participant-facing wording

Public: Visible to anyone on the internet. Public content may appear in search
engines and may be collected by automated web scrapers, including AI systems.
Copies may remain elsewhere after you change its visibility.

Participants only: Visible to approved Deadletter participants and organizers,
not anonymous visitors. Participants can still copy, photograph, or share it.
This is not confidential or end-to-end encrypted.

Social address: Your social address and delivery-location information are
visible only to approved participants and organizers regardless of the
public-content setting.

Physical project: Website settings do not prevent people handling printed
letters from reading, photographing, or sharing them.

## Implementation sequence

1. Policy foundation (this slice).
2. Additive account/content/source/claim models, separate historical-data
   migration, and migration tests; back up the development database first.
3. Registration, review queue, and account preference screens.
4. Request/body forms, approved-participant checks, public field projections,
   protected media, and end-to-end access tests. Existing anonymity tests are
   intentionally updated only when enforcement is wired.
5. Account linking/claiming and sensitive-content warning/restriction flows.
6. Rate limiting, then deployment validation.

Keep main unchanged. No EC2 launch before the integrated access model passes.
