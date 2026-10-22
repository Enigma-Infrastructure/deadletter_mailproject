# deadletter_mailproject

## Running locally

The project runs on **Python 3.13**. Two ways to set up the environment:

### Option A — conda env (current setup)

```
conda create -n DeadletterMail python=3.13
conda activate DeadletterMail
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Or run the env's Python directly (no activation needed):

```
C:\Users\Prism\anaconda3\envs\DeadletterMail\python.exe manage.py runserver
```

If you prefer `conda activate`, initialize it once in cmd:
`C:\Users\Prism\anaconda3\Scripts\conda.exe init cmd.exe`, open a new
window, then `conda activate DeadletterMail` and `python manage.py runserver`.

### Option B — venv

```
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Unix
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### Secret key (optional for local dev)

The secret key is read from the environment, never hardcoded. If
`DJANGO_SECRET_KEY` is unset, a random per-process key is generated so the
server runs without manual setup. Set it for a stable key (production, or to
persist sessions across restarts):

```
set DJANGO_SECRET_KEY=<a-long-random-string>    # Windows cmd
# export DJANGO_SECRET_KEY=<a-long-random-string>   # Unix
```

`DEBUG` defaults to `true` for local development; set `DJANGO_DEBUG=false`
when deploying.

## Reproducibility

- `requirements.txt` lists the Python dependencies. After your env is working,
  pin exact versions for full reproducibility: `pip freeze > requirements.txt`.
- The database is SQLite (`db.sqlite3`), created by `python manage.py migrate`.
- `ALLOWED_HOSTS` is `localhost`/`127.0.0.1` for local development; add your
  domain here when deploying.

## Troubleshooting

- **"Couldn't import Django"** — the env isn't activated or `requirements.txt`
  wasn't installed. Activate the env and `pip install -r requirements.txt`.
- **`DJANGO_SECRET_KEY` error** — set the environment variable (see above).
- **Missing tables / `OperationalError: no such table`** — run
  `python manage.py migrate`.
- **Static CSS not loading** — `STATICFILES_DIRS` includes `static/`; restart
  the server. In production you'd `collectstatic`.
- **Port 8000 busy** — `python manage.py runserver 8001` (or another port).
- **Python version** — 3.13 is required; check with `python --version`.

## Viability checks

Run these to confirm the project is healthy:

```
python manage.py check          # validates settings, models, URLs
python manage.py migrate        # applies any pending migrations
python manage.py test           # runs the test suite (currently empty)
python manage.py runserver      # start the server
```

Then visit the entry points below and confirm each renders.

## Key entry points

- **Request a letter** (public intake): http://127.0.0.1:8000/write/request/
- **Writing desk** (public, iPad-friendly): http://127.0.0.1:8000/letters/desk/
- **Scan a letter** (public, general QR landing): http://127.0.0.1:8000/scan/
- **Carry / courier list**: http://127.0.0.1:8000/letters/carry/
- **Courier leaderboard**: http://127.0.0.1:8000/leaderboard/
- **Print queue** (staff): http://127.0.0.1:8000/letters/print/queue/
- **Django admin**: http://127.0.0.1:8000/admin/

## Core concepts

- **Pirate mail address** — a social place where someone can be found (bar,
  cafe, camp, venue, group...). NOT a street address. Modeled as
  `people.Place`; mail is handed to someone who knows the recipient there.
- **Stamp** — a physical stamp with a unique number affixed to each letter.
  Its QR points at `/scan/<number>/` where anyone can log what happened to
  the letter (spotted / picked up / left / delivered), add a photo, or tag
  their Instagram. Movement updates drive the courier chain (`LetterHop`)
  and the letter's status.
- **Print pipeline** — letters written digitally (desk/iPad or online) enter
  the print queue (`needs_printing`); printing a batch issues stamps and
  releases the letters into the physical world.
- **Game layer** — logged-in couriers earn points for keeping letters moving;
  leaderboard at `/leaderboard/`.
