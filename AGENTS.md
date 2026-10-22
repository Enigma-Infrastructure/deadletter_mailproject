# AGENTS.md — deadletter_mailproject

## Domain Glossary

| Term | Meaning |
|------|---------|
| **Pirate mail address** | A *social* location (bar, cafe, camp, venue, volunteer group, nonprofit, art group, bookstore, band, choir, bistro) where a person can be found. **Not a postal address.** Mail reaches a person by being handed to someone at this place who knows them. |
| **Place** | A `people.Place` row: `name`, `kind` (free-text, e.g. bar/cafe/bookstore/venue), `city`, `description`. Unique on `(name, city)`. |
| **Person** | A `people.Person` row: `nickname`, `pirate_place` FK→Place, `city`, `write_about`, `email`. Unique on `(nickname, pirate_place)`. The `pirate_address_display` property renders the human-readable address. |
| **LetterConcept** | The *idea* of a letter — title, description, write_prompt, destination_place, destination_city, created_for. A concept can spawn many physical instances. |
| **LetterInstance** | A *specific copy* of a concept with a unique `code` (10-char random string) and QR. Has `body_text`, `status`, `origin`, `needs_printing`, `is_public`. |
| **Letter status flow** | `created` → `waiting_print` → `waiting_stamp` → `waiting_carrier` → `traveling` → `left` → `delivered` → `archived`. |
| **Stamp** | A QR token attached to a letter instance. Has a `number` (8-char from unambiguous alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`), `is_active`, `created_at`. |
| **StampUpdate** | A reactive event on a stamp: `kind` (spotted/picked_up/left/delivered/photo/note), `place`, `instagram_handle`, `media` FK→MediaItem, `submitted_by`. |
| **LetterHop** | Drives the courier chain — records which carrier picked up the letter and where it was left. |
| **ReputationEvent** | Append-only ledger of courier engagement. `reason` (spotted/photo/picked_up/left_at_place/delivered/note/organizer), `reputation` (points), `letter`, `network`. **Never stored as a running total** — the leaderboard is computed by aggregation via `ReputationEvent.leaderboard()`. |
| **ReputationNetwork** | A scope in which reputation is earned and ranked (per-event, per-city, global). |
| **Topic / LetterTopic** | `topics.Topic` (name, description, icon) and `topics.LetterTopic` (canonical link between a LetterConcept and a Topic, unique on both). |
| **MediaItem** | `media_app.MediaItem` — photo attached to a letter: `kind` (writer/carrier/envelope_front/envelope_back/arrival/other), `file`, `captured_at`, `latitude`/`longitude`, `caption`, `hashtags`, `uploaded_by`. |
| **Origin** | How a letter was created: `desk` (Writing desk / iPad at an event), `online` (Online submission), `admin` (Admin / organizer). |

## Conventions

### View structure
- Views are **function-based** (not class-based) except for the DRF API view (`LettersInMyAreaAPIView`).
- Each view file has section comments (`# ---`) grouping related views.
- Public views (no login required): `write_read_home`, `letter_write_queue`, `letter_write_claim`, `letter_write_confirm`, `letter_read_list`, `desk_read_list`, `scan_home`, `scan_stamp`, `request_a_letter`, `leaderboard`.
- Staff-only views: `print_queue`, `print_batch`, `print_confirm`, `letter_print_view`, `admin_hub`.
- Collaborator-only views: `recipient_list` (via `@user_passes_test(is_collaborator)`).

### Template naming
- Templates live in `templates/` at the project root (not per-app).
- Subdirectories mirror the app: `templates/letters/`, `templates/people/`, `templates/desk/`, `templates/registration/`.
- Base template: `templates/base.html` — extends `{% block content %}`.
- Desk templates extend `templates/desk/desk_base.html`.
- Login template: `templates/registration/login.html`.

### URL patterns
- Root: `deadletter_mailproject/urls.py` — `""` home, `admin/hub/`, `admin/`, `accounts/` (auth urls), `leaderboard/`, `scan/` + `scan/<str:number>/`, `write/` (people.urls), `letters/` (letters.urls).
- `people/urls.py` — `""` redirects to `/write/request/`, `request/`, `recipients/`.
- `letters/urls.py` — `read/`, `write/queue/`, `write/claim/<int:pk>/`, `write/confirm/<str:code>/`, `print/queue/`, `print/batch/`, `print/confirm/`, `print/<str:code>/` (must come AFTER queue/batch), `l/<str:code>/`, `carry/`, `api/letters/`, `desk/`, `desk/read/`.

### Model conventions
- All FKs to the user model use `settings.AUTH_USER_MODEL` (never `django.contrib.auth.models.User`).
- `related_name` is always set on FKs.
- `on_delete` is `SET_NULL` for optional FKs, `CASCADE` for required FKs.
- `auto_now_add=True` for `created_at` timestamps.
- `ordering` is set in `Meta` for most models.

### Form conventions
- `LetterBodyForm` — single `body_text` textarea with Markdown support.
- `ScanUpdateForm` — validated form for the public scan/update endpoint; validates photo size (max 5 MB) and content type (JPEG/PNG/WebP/GIF).

### Serializer conventions
- `PersonPublicSerializer` — exposes `pirate_address` via `SerializerMethodField` calling `pirate_address_display`.
- `LetterConceptSerializer` — exposes `destination_place` via `SerializerMethodField` calling `destination_display`.
- `LetterInstanceSerializer` — exposes `current_location` and `stamp_numbers` via `SerializerMethodField`.

## Gotchas

### Custom user model
- `AUTH_USER_MODEL = "accounts.User"` — the project uses a **custom user model** (`accounts.User(AbstractUser)` with `is_collaborator`).
- **Never import `django.contrib.auth.models.User`** — always use `settings.AUTH_USER_MODEL` or `accounts.User`.
- The `is_collaborator` flag gates access to `recipient_list` and other collaborator-only views.

### nh3 sanitization
- `nh3` is used to sanitize Markdown output. Letter `body_text` is stored as raw Markdown and rendered through `nh3` to prevent XSS.
- Do not render `body_text` directly as HTML — always sanitize through `nh3`.

### easymde editor
- `easymde` (EasyMDE) is the Markdown editor used in the writing desk and claim pages.
- The editor adds a toolbar and preview to the `LetterBodyForm` textarea.
- The form field has `id="id_body_text"` — the editor attaches to this ID.

### QR code
- `qr_code` (django-qr-code) generates QR codes for letter instances and stamps.
- The QR encodes the letter `code` (10-char) or stamp `number` (8-char).
- The public landing page (`/letters/l/<str:code>/`) shows the letter content and QR.

### Letter code vs stamp number
- `LetterInstance.code` — 10-char random string (`get_random_string(10)`), unique.
- `Stamp.number` — 8-char from unambiguous alphabet `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (`get_random_string(8, allowed_chars=alphabet)`), unique.
- These are **different** identifiers. The letter code is the primary identifier; the stamp number is the QR token.

### Reputation is append-only
- `ReputationEvent` is an **append-only ledger**. There is no running total on the user.
- `ReputationEvent.award()` classmethod creates a new event with default points: spotted 5, photo 5, picked_up 10, left_at_place 15, delivered 25, note 2, organizer 0.
- `ReputationEvent.leaderboard()` aggregates by `user__username` and returns top N by total reputation.
- Anonymous scans earn no reputation (no user to credit).

### Place is NOT a postal address
- `Place` is a **social location** — a bar, cafe, camp, venue, etc.
- The `description` field explains how a courier would actually find/hand off mail there.
- `Person.pirate_place` is the social location where the person can be found.
- `LetterConcept.destination_place` is the social location where the letter should arrive.

### Letter status transitions
- Status changes are driven by the physical production pipeline and courier chain.
- `waiting_print` → `waiting_stamp` (after printing).
- `waiting_stamp` → `waiting_carrier` (after stamping).
- `waiting_carrier` → `traveling` (after carrier picks up).
- `traveling` → `left` (after carrier leaves at destination).
- `left` → `delivered` (after recipient picks up).
- `delivered` → `archived` (after archiving).

### Media upload
- `MediaItem.file` uploads to `letters/` under `MEDIA_ROOT` (`BASE_DIR / "media"`).
- Photo validation: max 5 MB, JPEG/PNG/WebP/GIF only.
- `latitude`/`longitude` are optional GPS coordinates.

### Cache
- `CACHES` uses `LocMemCache` (in-memory) for rate limiting in dev.
- Use Redis for production.

### Login redirect
- `LOGIN_URL = "/accounts/login/"`
- `LOGIN_REDIRECT_URL = "/letters/desk/"` — after login, users are redirected to the writing desk.

## Environment

### Conda environment
- **Env name:** `DeadletterMail`
- **Path:** `C:\Users\Prism\anaconda3\envs\DeadletterMail`
- **Python:** 3.13.13

### Activation
```powershell
conda activate DeadletterMail
```

### Running the server
```powershell
python manage.py runserver
```
- Server runs at `http://127.0.0.1:8000/`.
- `DEBUG` defaults to `True` (set `DJANGO_DEBUG=false` for production).
- `SECRET_KEY` from `DJANGO_SECRET_KEY` env var (random per-process fallback).
- `ALLOWED_HOSTS` is `localhost`/`127.0.0.1` for local dev.

### Database
- SQLite: `BASE_DIR / "db.sqlite3"`.
- Run migrations: `python manage.py migrate`.

### Key entry points
| URL | Purpose |
|-----|---------|
| `/` | Landing page (project description) |
| `/write/request/` | Public intake form (request a letter) |
| `/letters/desk/` | Writing desk (pending concepts) |
| `/letters/read/` | Read letters (public) |
| `/letters/carry/` | Carry / courier list |
| `/scan/` | Scan a stamp (QR landing) |
| `/scan/<number>/` | Scan a specific stamp |
| `/leaderboard/` | Courier leaderboard |
| `/letters/print/queue/` | Print queue (staff) |
| `/letters/print/batch/` | Print batch (staff) |
| `/admin/` | Django admin |
| `/admin/hub/` | Admin hub (staff) |

### Requirements
- `Django>=6.1`
- `djangorestframework`
- `django-qr-code`
- `django-easymde`
- `markdown`
- `nh3`
- `Pillow`
