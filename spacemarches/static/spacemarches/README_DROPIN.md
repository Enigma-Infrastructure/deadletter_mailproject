# `mesh-net` Point-Buy v2 Static Bundle (`spacemarches/static/spacemarches/`)

This directory holds the compiled **Mesh-Net Point-Buy v2** frontend bundle (built from the SolidJS + UnoCSS + Lingui `TheGam1ngWizard/mesh-net` codebase), Material Design 3 dynamic palette engine (`spacemarches-palette.js`), and stylesheet (`spacemarches-theme.css`) served by Django at `/spacemarches/meshnet/`, `/spacemarches/generator/`, and `/spacemarches/terminal/`.

For cross-agent EP2E content migration status and handoff details, see `docs/spacemarches-meshnet-handoff.md`.

## Bundle Notes

- Built with `base: "/static/spacemarches/"`, `HashRouter` (`#/...`), and PWA / Workbox service workers disabled (`sw.js` and `workbox-*.js` stripped) so Django's `@login_required` and session/CSRF flows remain intact.
- Entry assets live in `spacemarches/static/spacemarches/assets/` (`index-*.js` and `index-*.css`) and are resolved automatically by `_resolve_meshnet_bundle()` in `spacemarches/views.py`.
- **Django ↔ MeshNet hooks (must remain compatible across rebuilds):**
  - `window.__SPACEMARCHES_BOOT__` — server bootstrap payload (`authenticated`, `saved_characters`, `dossiers`, `characters_api_url`, etc.)
  - `window.SpacemarchesBridge` — `AgentSaveSlot` localStorage sync bridge (`/spacemarches/api/sync/`)
  - `window.SpacemarchesTheme.syncFromMeshNet(presetKey, colorMode)` — keeps the unified Django header palette/contrast drawer synchronized with MeshNet's internal theme state
  - Single-scroll viewport: `terminal.html` locks `html, body { overflow: hidden; }` and constrains MeshNet's internal scrollable container to `#root`.

## Production Static Collection

```bash
python manage.py collectstatic --noinput
```
