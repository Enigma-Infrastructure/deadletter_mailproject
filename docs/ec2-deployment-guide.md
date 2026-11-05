# EC2 Production Deployment Guide — deadletter_mailproject

This guide details deploying `deadletter_mailproject` to an Amazon Linux / Ubuntu EC2 instance behind an Nginx reverse proxy with Gunicorn and systemd.

---

## 1. Environment Setup

### 1.1 Python & System Packages
Install Python 3.13 (or system Python 3), virtual environment tools, and Nginx:

```bash
sudo apt-get update && sudo apt-get install -y python3-venv python3-pip nginx certbot python3-certbot-nginx
```

### 1.2 Application Directory
Set up the application directory and storage paths:

```bash
sudo mkdir -p /var/www/deadletter/staticfiles /var/www/deadletter/media
sudo chown -R ubuntu:www-data /var/www/deadletter
sudo chmod -R 775 /var/www/deadletter/media
```

Clone the repository and install dependencies in a dedicated virtualenv:

```bash
cd /var/www/deadletter
git clone -b production-readiness https://github.com/Enigma-Infrastructure/deadletter_mailproject.git app
python3 -m venv venv
source venv/bin/activate
pip install -r app/requirements.txt gunicorn
```

---

## 2. Configuration & Environment Variables

Create `/var/www/deadletter/.env` (read-only by the application user, `chmod 600`):

```bash
# Security
DJANGO_SECRET_KEY="<generate-at-least-50-character-random-secret-key>"
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS="yourdomain.org,www.yourdomain.org"
DJANGO_TRUST_PROXY_HTTPS=true

# Storage Paths (must be absolute paths)
DJANGO_STATIC_ROOT=/var/www/deadletter/staticfiles
DJANGO_MEDIA_ROOT=/var/www/deadletter/media
DJANGO_DB_PATH=/var/www/deadletter/db.sqlite3
```

---

## 3. Pre-Flight Verification & Asset Collection

Run the deployment configuration check and collect static assets:

```bash
export DJANGO_SETTINGS_MODULE=deadletter_mailproject.settings_production
set -a && source /var/www/deadletter/.env && set +a

# 1. Run deployment checks
python app/manage.py check --deploy --settings=deadletter_mailproject.settings_production

# 2. Collect static files
python app/manage.py collectstatic --no-input --settings=deadletter_mailproject.settings_production

# 3. Apply database migrations
python app/manage.py migrate --settings=deadletter_mailproject.settings_production
```

---

## 4. Systemd Service Unit

Create `/etc/systemd/system/deadletter.service`:

```ini
[Unit]
Description=Deadletter Mailproject Gunicorn Application Server
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/deadletter/app
EnvironmentFile=/var/www/deadletter/.env
Environment="DJANGO_SETTINGS_MODULE=deadletter_mailproject.settings_production"
ExecStart=/var/www/deadletter/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:8000 \
    --access-logfile /var/log/deadletter/access.log \
    --error-logfile /var/log/deadletter/error.log \
    deadletter_mailproject.wsgi:application

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo mkdir -p /var/log/deadletter
sudo chown ubuntu:www-data /var/log/deadletter
sudo systemctl daemon-reload
sudo systemctl enable --now deadletter
sudo systemctl status deadletter
```

---

## 5. Nginx Reverse Proxy Configuration

Create `/etc/nginx/sites-available/deadletter`:

```nginx
server {
    listen 80;
    server_name yourdomain.org www.yourdomain.org;

    client_max_body_size 5M;

    # Static assets
    location /static/ {
        alias /var/www/deadletter/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    # Media uploads
    location /media/ {
        alias /var/www/deadletter/media/;
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
    }

    # Proxy to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }
}
```

Enable the site and configure SSL:

```bash
sudo ln -s /etc/nginx/sites-available/deadletter /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.org -d www.yourdomain.org
```

---

## 6. Operational Checklist

- [ ] **HTTPS Enforced:** SSL redirect is active (`SECURE_SSL_REDIRECT=True` via `settings_production.py`).
- [ ] **Cookies Secure:** Session and CSRF cookies marked `Secure` and `HttpOnly`.
- [ ] **Proxy Headers:** Nginx passes `X-Forwarded-Proto $scheme` and `DJANGO_TRUST_PROXY_HTTPS=true` is set.
- [ ] **Upload Size:** Nginx `client_max_body_size` aligns with Django upload limit (5MB).
- [ ] **Database Backups:** Daily automated snapshot/backup of `/var/www/deadletter/db.sqlite3`.
