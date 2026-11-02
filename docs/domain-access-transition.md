# Persisted access adapters before workflow cutover

## Scope
This additive batch supplies letters.domain_access and database-backed tests. It does NOT wire views, change public behavior, publish backfilled records, edit models, generate migrations, or synchronize legacy writes. The user reported 88ec035 passed 112 tests, then applied four requests/two letters/two links and verified a zero-work preview. This batch's tests have not been run by the author.

## Rules
Use only a server-authenticated user. persisted_viewer rereads is_active and participant_status from the selected database; stale user approval, staff/superuser flags, ownership, authorship, email verification and registration source are not approval. Anonymous/inactive/unapproved users have only the anonymous public audience; approval is not required to read already public unrestricted content.

readable_requests filters publication and known audience; readable_letters additionally applies its originating request's audience. Standalone letters use their own audience. Approved active participants may read published restricted content, matching the existing pure policy. Unpublished records remain hidden from audience reads including approved participants. Editing/admin preview authorization is a different future path. Missing records fail closed. Address helpers require approved active participation AND readable content. These helpers do not grant print, courier-update or edit permissions.

Querysets contain full private models, not safe response objects. Never pass them directly to public templates or serializers without field-level redaction. Request/body readability does not expose destination snapshots, Person relationships, emails, media, notes, journeys, tracking codes or addresses. The helpers do not consult legacy is_public; they are not a replacement for existing physical-route guards. Until cutover, keep those guards in place.

A queryset captures viewer approval when constructed. Construct/evaluate it in the same short request; do not cache or reuse it across requests or approval changes. This is not a transaction-wide authorization snapshot or a guarantee against concurrent revocation. Use the same explicit database alias for viewer and content.

## Local validation
```
git pull --ff-only &&
python manage.py check &&
python manage.py makemigrations --check --dry-run &&
python manage.py migrate --plan &&
python manage.py test letters.test_domain_access letters.test_access_policy letters.test_source_backfill &&
python manage.py test &&
python manage.py audit_letter_sources --json &&
python manage.py backfill_letter_sources
```
No migrations or data changes are expected. The local audit should still show four requests/two letters/two links, no publication, and the backfill preview should plan zero work if source data is unchanged. Tests compare persisted SQL decisions against the pure policy matrix; cover approval revocation, inactive/deleted users, no role/owner bypass, standalone works, publication, social-address gates and read-only queries.

## Next integration boundaries
1. Add transactional write services and explicit attribution rules for request creation and authored response creation, with duplicate-submission behavior defined. Do not silently resynchronize edited new records.
2. Inventory every read/output path before cutover: writing queues/claim/confirmation, browse/desk/public detail, print/envelope, scan GET/POST, carry list, API, serializers, templates, media URLs, admin and caches. Introduce field-level presentation objects and separate social-address authorization. Search/filter/count output must use the same audience.
3. Preserve physical is_public restrictions and decide approved-reader behavior explicitly; do not weaken legacy guards or assume participant permission to make courier updates/print. Test both HTTP methods and side effects.
4. Define publication/restriction review, owner/writer draft access, write synchronization and source-of-truth cutover together before switching routes. Backfilled records intentionally remain unpublished; direct route switching would hide them.
5. Validate all paths, then perform a separate reviewed cutover. This batch alone does not make the application participant-private or production-ready.
