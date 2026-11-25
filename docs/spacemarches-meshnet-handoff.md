# Spacemarches & MeshNet — Cross-Agent Status Tracker & Engineering Handoff

**Last updated:** 2026-11-25  
**Repository:** `Enigma-Infrastructure/deadletter_mailproject`  
**Active branch:** `production-readiness` (synced after `822b5b6`; `main` remains at `3cd4abc`, 63 commits behind)  
**Primary local environment:** Windows, Conda env `DeadletterMail` (`Python 3.13`), SQLite dev DB

This document is the single cross-agent tracking and handoff source for **Spacemarches**, **MeshNet**, **EP2E content migration**, and related paused tracks in `deadletter_mailproject`. Keep it updated with actual commit SHAs, file paths, and local test results after each batch.

---

## 1. Program Status Matrix (Current Priorities)

| Track | Status | Scope / Blocker | Next Action |
| --- | --- | --- | --- |
| **MeshNet (Point-Buy v2 + EP2E Content Migration)** | **IN PROGRESS (Active Focus)** | **Backend DB seeding landed in `822b5b6`:** `Ep2Entry` (`0006_ep2entry`), `ep2_entries.json` (**1,042 entries across all 55 `Bubz43/ep2e` Foundry packs**), `seed_ep2_data`, and `/spacemarches/api/ep2/`. **Frontend gap remains:** the compiled MeshNet bundle in `spacemarches/static/spacemarches/` still uses its partial built-in `data-crb`/`data-copt` packs (infomorphs only, partial gear) and does not yet consume `/spacemarches/api/ep2/` or include COPT / MeshNet-specific packs. | Run `migrate` + `seed_ep2_data` + `test_ep2_data` locally; decide whether MeshNet consumes `/spacemarches/api/ep2/` at runtime or ports missing CRB/COPT packs from `ep2e-virtual` / `Ep2Entry` into `mesh-net` and rebuilds the static bundle; review committed binary source docs in `822b5b6`. |
| **Life-Path Character Creator** | **QUEUED (After EP2E Core + MeshNet)** | `GeneratedCharacter.SOURCE_LIFE_PATH` enum/scaffolding already exists in `spacemarches/models.py` and `character_sync_service.py`; full 15-step Life-Path UI & 14 tables live in `TheGam1ngWizard/ep2e-virtual` (`packages/life-path`, `packages/character-options`). | Port Life-Path tables and 15-step wizard after EP2E core content & Point-Buy v2 creator are complete. |
| **Spacemarches Discord Bot (`run_discord_bot.py`)** | **PAUSED** | Persistent views, `/link`, `/dossier`, `/intake`, `/debrief`, and `start_discord.cmd` are implemented. Paused until character creator & EP2E content stabilize. | Later: add read/sheet commands (`/dossier sheet` / stats lookup) pulling linked `GeneratedCharacter` summaries. |
| **Misago Forum SSO (OAuth2 IdP)** | **PAUSED** | Phase 1 (Django `django-oauth-toolkit` IdP + `/accounts/oauth/userinfo/` + `docs/misago-oauth-setup.md`) is complete on `production-readiness`. Paused while user sets up Docker for Misago. | Later: register Misago OAuth2 app in `/admin/oauth2_provider/application/` and test end-to-end SSO login. |
| **Deadletter Mail (Core Physical Mail App)** | **BACKBURNER** | Domain privacy, screening, rate limiting, and unwired `letters/staged_http.py` / `staged_urls.py` are implemented on `production-readiness` (see `deadletter_mail_engineering_handoff.md`). | Hold live route cutover and `docs/reputation-backlog.md` until Spacemarches focus shifts back. |
| **Production Deployment (InMotion / EC2)** | **PAUSED** | `settings_production.py` (HSTS, secure cookies) and `docs/ec2-deployment-guide.md` are ready. Waiting for InMotion server migration to finish. | Provision server, run `migrate` + `seed_ep2_data` + `collectstatic`, move DB/media outside checkout, and switch cache from `LocMemCache` to Redis. |

---

## 2. Review of Recent Local Work (`822b5b6`) & EP2E Content Migration State

Never commit GitHub tokens or secrets into any repository file. Local agents inspecting upstream repos should use local git credentials or environment-configured auth.

### What `822b5b6` ("local agentic work - needs review") Landed
- **Model & Migration:** `Ep2Entry` (`spacemarches/models.py`, `spacemarches/migrations/0006_ep2entry.py`) storing `source`, `pack`, `entry_id` (unique), `name`, `entry_type`, `category`, `description`, `reference`, and verbatim Foundry `system` JSON.
- **Fixture & Attribution:** `spacemarches/fixtures/ep2_entries.json` (**1,042 entries across 55 packs**: `gear`: 658, `trait`: 133, `character`: 69, `sleight`: 68, `substance`: 57, `morph`: 41, `misc`: 11, `special`: 5) + `spacemarches/fixtures/ATTRIBUTION.md` (CC BY 4.0).
- **Seed Command & API:** `python manage.py seed_ep2_data` (`--dry-run`, `--fixture`), `Ep2EntryAdmin`, read-only `GET /spacemarches/api/ep2/` & `/spacemarches/api/ep2/<entry_id>/`, and `spacemarches/test_ep2_data.py`.

### Review Findings & Follow-Ups from `822b5b6`
1. **Binary source files committed:** `822b5b6` also committed `EP2_MultiplicityandSynthesis_Patreon.pdf` (986 KB) and a `.docx` questionnaire in `spacemarches/`. Confirm whether the Patreon PDF should stay in git or be moved out / `.gitignore`d for licensing hygiene.
2. **Minor backend cleanups in `822b5b6`:**
   - `spacemarches/management/commands/seed_ep2_data.py` calls `self.exit(1)` on missing fixture; Django `BaseCommand` expects `raise CommandError(...)`.
   - `views._serialize_ep2_entry()` hardcodes `"source_url": "https://github.com/Bubz43/ep2e/tree/master/src/packs"` — once `mesh-net` / `ep2e-virtual` / Character Options rows are added with a distinct `source` value, derive `source_url` from `entry.source`.
3. **Frontend wiring gap (MeshNet ↔ `Ep2Entry`):**
   - `spacemarches/static/spacemarches/assets/` still runs the compiled `TheGam1ngWizard/mesh-net` bundle, which does not yet query `/spacemarches/api/ep2/`.

### Upstream Reference Repositories Reviewed (2026-11-25)

1. **`Bubz43/ep2e`** (Foundry VTT 1.0 system — `88474c5`)
   - Source of all 55 packs now imported into `spacemarches/fixtures/ep2_entries.json` (`source="bubz-ep2e"`).
2. **`TheGam1ngWizard/mesh-net`** (2.0 SolidJS + UnoCSS + Lingui + Dexie rewrite — `c16fbf4`)
   - Upstream source of the compiled bundle in `spacemarches/static/spacemarches/`.
   - **Already in `packages/data-crb` (35 files):** skills, skill packs, rep networks, ALIs, premade characters/egos, traits/disorders/neural damage, psi (`chi`, `gamma`, `substrain`, + `epsilon` in `data-crb-gm`), **infomorphs only** (`crb-digital-form-designs.tsx`), and **partial gear** (beam weapons, kinetic weapons, services, software, weapon accessories, substances).
   - **Already in `packages/data-copt` (4 files):** **only** COPT positive & negative traits.
   - **Still missing from MeshNet's own design-pack catalog:** CRB biomorphs/pod-biomorphs/uplift-morphs/synthmorphs/robots, CRB armor/exoskeletons/augmentations/melee/explosives/railguns/comms/meshware/fabbers/vehicles/creatures, and COPT morphs/augmentations (all now available on the Django side via `Ep2Entry` for CRB, plus `ep2e-virtual` for COPT + Life-Path).
3. **`TheGam1ngWizard/ep2e-virtual`** (Earlier monorepo — `04e1c94`)
   - Contains structured TypeScript definitions ready for porting into `mesh-net`:
     - `packages/core-repo/src/design-pack/sections/` — full CRB morphs, gear, armor, augmentations, vehicles, skills, sleights, traits
     - `packages/character-options/src/design-pack/sections/` — COPT augmentations, biomorphs, infomorphs, synthmorphs, positive/negative traits
     - `packages/character-options/src/life-path-data/` — **14 Life-Path data tables**
     - `packages/life-path/src/` — **15-step Life-Path character creator** (`LifePathStep1EgoFlex` → `LifePathStep15FinalStatsAndDetails`)

---

## 3. MeshNet ↔ Django Integration Contract (`deadletter_mailproject`)

Important architectural boundary: **`deadletter_mailproject` only stores the compiled MeshNet frontend bundle** under `spacemarches/static/spacemarches/`. The SolidJS/UnoCSS/Lingui source code lives in the separate `mesh-net` workspace.

### Files & Entry Points in `deadletter_mailproject`
- **Routes (`spacemarches/urls.py`):**
  - `/spacemarches/meshnet/` & `/spacemarches/generator/` → public Point-Buy v2 shell (`views.generator`)
  - `/spacemarches/terminal/` → authenticated legacy shell (`views.terminal`)
  - `/spacemarches/characters/` → authenticated roster (`views.character_roster`, supports `.json` upload)
  - `/spacemarches/characters/<pk>/export/?format=html|json|md` → sheet exports
  - `/spacemarches/characters/<pk>/link/` & `/delete/` → Dossier linking & deletion
  - `/spacemarches/api/ep2/` & `/spacemarches/api/ep2/<entry_id>/` → read-only EP2E reference data API (`Ep2Entry`)
  - `/spacemarches/api/characters/` (`GET`, `POST` single or batch `{"characters": [...]}`), `/spacemarches/api/characters/<pk>/` (`GET`, `DELETE`), `/spacemarches/api/characters/<pk>/link-dossier/` (`POST`)
  - `/spacemarches/api/sync/` (`GET`, `POST`) → `AgentSaveSlot` localStorage cloud sync
- **Bundle Resolution (`_resolve_meshnet_bundle` in `spacemarches/views.py`):**
  - Automatically resolves `spacemarches/static/spacemarches/assets/index-*.js` and `index-*.css` (falling back to `index.js` / `index.css`).
  - **Build rules for any MeshNet drop-in update:**
    1. Build with `base: "/static/spacemarches/"` and `HashRouter` (`#/...`).
    2. **Strip/disable PWA & Workbox service workers** (`sw.js`, `workbox-*.js`) so Django `@login_required`, CSRF cookies, and `/accounts/` auth flows are never intercepted by a cached service worker.
    3. Keep `window.__SPACEMARCHES_BOOT__`, `window.SpacemarchesBridge`, and `window.SpacemarchesTheme.syncFromMeshNet(presetKey, colorMode)` intact (see `spacemarches/templates/spacemarches/terminal.html` and `spacemarches/static/spacemarches/spacemarches-palette.js`).
    4. Keep single-scroll layout compatibility: `terminal.html` locks `html, body { overflow: hidden; }` and expects MeshNet's internal scrollable container (`overflow-y-auto`) to fill `#root`.
- **Character Persistence (`spacemarches/services/character_sync_service.py`):**
  - `extract_point_buy_summary(raw_data)` parses Point-Buy v2 JSON (`character.ego`, `pointBuy`, `designPacks` / `packs`) into normalized `summary` fields (`aptitudes`, `flex`, `skill_packs`, `morphs`, `traits`, `sleights`, `reputations`, `languages`, `motivations`, `skill_count`).
  - **When adding new EP2E content (biomorphs, synthmorphs, gear, augmentations, or future Life-Path sheets):** verify that `raw_data` design-pack/morph/trait keys resolve cleanly through `extract_point_buy_summary()`, `export_generated_character_markdown()`, and `export_generated_character_html()`, and extend `spacemarches/test_generated_characters.py`.

---

## 4. Database & Schema State

- **Committed `db.sqlite3` note:** The tracked `db.sqlite3` in git only contains 23 legacy tables (through migration batch 44). It does **not** include `spacemarches_*`, `oauth2_provider_*`, `letters_letterrequest`, or `accounts_registrationsource`.
- **On any local checkout after pulling `production-readiness`:**
  1. Install updated dependencies (`django-oauth-toolkit>=3.4`, `discord.py>=2.3`, etc.).
  2. Run `python manage.py migrate`.
  3. Run `python manage.py seed_ep2_data --dry-run` and then `python manage.py seed_ep2_data` to load the 1,042 `Ep2Entry` rows.
- **Spacemarches schema inventory:**
  - `spacemarches/fixtures/ep_questionnaire_schema.json`: 98 questions (`16` core, `76` deep, `6` sensitive_appendix `13d1–13d6`; temporal scopes: `80` present, `10` origin, `5` timeless, `3` fall).
  - `spacemarches/fixtures/ep2_entries.json`: 1,042 EP2E reference entries across 55 packs (`source="bubz-ep2e"`).
  - `OperationSession` & `FieldAgent` (`spacemarches/models.py`): defined in models, admin, and `selectors.py`, not yet exposed in campaign gameplay views.
  - No seed fixtures exist yet for `ArchiveEntry` or `ForumThread`.

---

## 5. Local Dev Commands & Validation Checklist

Run from the repository root inside Conda env `DeadletterMail`:

```powershell
conda activate DeadletterMail
git status --short
git branch --show-current
git pull --ff-only origin production-readiness
pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
python manage.py seed_ep2_data --dry-run
python manage.py seed_ep2_data
python manage.py test spacemarches
python manage.py test
python manage.py runserver
```

Optional / targeted checks:
```powershell
python manage.py test spacemarches.test_ep2_data spacemarches.test_generated_characters spacemarches.test_views_and_selectors spacemarches.test_schema_and_services
python manage.py test accounts.test_oauth_idp
```

### Browser Smoke Checklist after MeshNet Bundle Drop-In
1. Visit `http://127.0.0.1:8000/spacemarches/`, `/spacemarches/meshnet/`, and `/spacemarches/api/ep2/?limit=5`.
2. Confirm no double vertical scrollbars inside MeshNet and that **Palette & Contrast** drawer toggles, presets, and light/dark/contrast modes stay in sync with MeshNet's internal theme.
3. Build/import a Point-Buy v2 character with newly migrated morphs/gear, verify anonymous export (HTML/MD/JSON), sign in, save to cloud (`/spacemarches/api/characters/`), verify `/spacemarches/characters/` roster rendering, and link to a `CharacterDossier`.

---

## 6. Handoff Rules for Local & Remote Agents

1. **Work on `production-readiness`** unless explicitly instructed to merge to `main`.
2. **Never commit secrets, API keys, `.env`, or GitHub PATs** into code, scripts, or markdown docs.
3. **Never infer test results** — record exact commands run, pass/fail/skip counts, and browser checks performed.
4. **Update Section 1 & add a checkpoint entry below** whenever a MeshNet bundle drop-in, EP2E content pack, or Django schema change lands.

### Checkpoints
- **`822b5b6` (2026-11-25):** Local agentic work — added `Ep2Entry` (`0006_ep2entry`), 1,042-entry `ep2_entries.json` fixture (`Bubz43/ep2e`), `seed_ep2_data`, `/spacemarches/api/ep2/`, `test_ep2_data.py`, and source PDF/DOCX attachments (needs local review & test run).
- **`338751d` (2026-11-25):** Fixed stuck palette indicator and single-scroll MeshNet layout (`spacemarches-palette.js`, `spacemarches-theme.css`, `terminal.html`). Follows `466906e` (`Powered by MeshNet` header + `run-django-site.cmd`), `aada6f4` (M3 theme normalization & unified header), and `5d41aaa` (MeshNet Point-Buy v2 + `GeneratedCharacter` persistence).
