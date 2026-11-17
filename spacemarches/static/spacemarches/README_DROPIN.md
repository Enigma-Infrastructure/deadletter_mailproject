# `mesh-net` Static Bundle Drop-In Instructions

This directory (`spacemarches/static/spacemarches/`) is the staged mount point for the compiled `mesh-net` interactive fiction / terminal frontend build.

## Extraction Steps

When the `mesh-net` distribution bundle is ready:

1. Extract the static bundle into this folder so assets resolve under:
   - `spacemarches/static/spacemarches/assets/` (compiled JS & CSS chunks, fonts, sprites)
   - `spacemarches/static/spacemarches/design-packs.html` (if referenced by iframe or pack loader)
2. **CRITICAL — Strip Service Workers & Offline Caches:**
   - **Delete** `sw.js`, `registerSW.js`, and any `workbox-*.js` files before committing or running `collectstatic`.
   - Service workers intercept navigation requests and break Django's `@login_required` session gate on `/spacemarches/terminal/` and `/spacemarches/api/sync/`.
3. **Wire Entry Bundles in `terminal.html`:**
   - Open `spacemarches/templates/spacemarches/terminal.html` and uncomment / point the `{% static 'spacemarches/assets/...' %}` `<link>` and `<script type="module">` tags to the built filenames (or a manifest/fixed entry filename).
   - Ensure the `window.SpacemarchesBridge` script runs **before** the `mesh-net` bundle executes so `localStorage` is hydrated from the user's `AgentSaveSlot` before the reducer initializes.
4. Run static collection in production:
   ```bash
   python manage.py collectstatic --noinput
   ```
