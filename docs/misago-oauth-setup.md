# Misago OAuth2 SSO Integration (Phase 1 -> Phase 2)

This repository (`deadletter_mailproject`) serves as the OAuth2 Identity Provider (IdP) for **Enigma Infrastructure Forums** (Misago) using `django-oauth-toolkit`.

## 1. Local & Production Pre-Flight
After pulling these changes, install the new dependency and run migrations so `oauth2_provider` tables exist:

```bash
pip install -r requirements.txt
python manage.py migrate
```

## 2. Register Misago as an OAuth2 Client
1. Sign into `/admin/` as a superuser (or navigate via `/admin/hub/` → **OAuth2 client applications**).
2. Add a new **Application**:
   - **Name:** `Enigma Infrastructure Forums`
   - **Client type:** `Confidential`
   - **Authorization grant type:** `Authorization code`
   - **Redirect uris:** `https://forums.<yourdomain>/oauth2/complete/` *(for local testing, `http://127.0.0.1:8001/oauth2/complete/`)*
   - **Skip authorization:** Checked (`True`) so first-party SSO doesn't prompt an extra consent screen
3. Copy the generated **Client ID** and plaintext **Client Secret** before saving (`client_secret` is stored hashed after save).

## 3. Misago Admin Panel → Settings → OAuth 2
- **Client ID / Secret:** From Step 2
- **Login / Authorization URL:** `https://projects.<yourdomain>/o/authorize/`
- **Access Token URL:** `https://projects.<yourdomain>/o/token/`
- **Scopes:** `read`
- **User data URL:** `https://projects.<yourdomain>/accounts/oauth/userinfo/`
- **JSON Mappings:**
  - User ID path: `id`
  - User name path: `username`
  - User e-mail path: `email`

> **PKCE Note:** `OAUTH2_PROVIDER["PKCE_REQUIRED"]` is explicitly `False` in `settings.py` so Misago's standard confidential Authorization Code flow does not fail with `Code challenge required`.
