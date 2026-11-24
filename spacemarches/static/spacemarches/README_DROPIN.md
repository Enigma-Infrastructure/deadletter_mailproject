# `mesh-net` Point-Buy v2 Static Bundle (`spacemarches/static/spacemarches/`)

This directory holds the compiled **Mesh-Net Point-Buy v2** frontend bundle, Material Design 3 dynamic palette engine (`spacemarches-palette.js`), and stylesheet (`spacemarches-theme.css`) served by Django at `/spacemarches/generator/` and `/spacemarches/terminal/`.

## Bundle Notes

- Built with `base: "/static/spacemarches/"`, `HashRouter` (`#/...`), and PWA / Workbox service workers disabled (`sw.js` and `workbox-*.js` stripped) so Django's `@login_required` and session/CSRF flows remain intact.
- Entry assets live in `spacemarches/static/spacemarches/assets/` and are resolved automatically by `_resolve_meshnet_bundle()` in `spacemarches/views.py`.
- `window.__SPACEMARCHES_BOOT__` and `window.SpacemarchesBridge` connect anonymous local IndexedDB characters and authenticated cloud saves/Dossier linking (`/spacemarches/api/characters/`).

## Production Static Collection

```bash
python manage.py collectstatic --noinput
```
