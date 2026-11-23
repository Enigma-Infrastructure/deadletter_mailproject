from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AccessToken, get_application_model

User = get_user_model()
Application = get_application_model()


class OAuth2IdentityProviderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="enigma-agent",
            password="Strong-OAuth-Password-99!",
            email="agent@example.org",
            participant_status="approved",
            is_collaborator=True,
        )
        User.objects.filter(pk=self.user.pk).update(email_verified=True)
        self.user.refresh_from_db()

        self.raw_secret = "misago-test-client-secret-value"
        self.app = Application.objects.create(
            name="Enigma Infrastructure Forums",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://forums.example.org/oauth2/complete/",
            client_secret=self.raw_secret,
            skip_authorization=True,
        )

    def test_management_endpoints_are_not_exposed_to_public(self):
        self.client.force_login(self.user)
        response = self.client.get("/o/applications/")
        self.assertEqual(response.status_code, 404)

    def test_userinfo_requires_valid_bearer_token(self):
        url = reverse("oauth_userinfo")
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_authorization_code_flow_without_pkce_and_userinfo_claims(self):
        # 1. Anonymous user hitting /o/authorize/ redirects to /accounts/login/
        auth_url = reverse("oauth2_provider:authorize")
        params = {
            "response_type": "code",
            "client_id": self.app.client_id,
            "redirect_uri": "https://forums.example.org/oauth2/complete/",
            "scope": "read",
            "state": "misago-csrf-state-123",
        }
        anon_res = self.client.get(auth_url, params)
        self.assertEqual(anon_res.status_code, 302)
        self.assertIn("/accounts/login/", anon_res["Location"])

        # 2. Logged-in user authorizes WITHOUT code_challenge (Misago #1257 compatibility)
        self.client.force_login(self.user)
        auth_res = self.client.get(auth_url, params)
        self.assertEqual(auth_res.status_code, 302)
        redirected = urlparse(auth_res["Location"])
        self.assertEqual(redirected.netloc, "forums.example.org")
        query = parse_qs(redirected.query)
        self.assertEqual(query.get("state"), ["misago-csrf-state-123"])
        code = query["code"][0]

        # 3. Misago exchanges code at /o/token/ with client_id + client_secret (no code_verifier)
        token_res = self.client.post(
            reverse("oauth2_provider:token"),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://forums.example.org/oauth2/complete/",
                "client_id": self.app.client_id,
                "client_secret": self.raw_secret,
            },
        )
        self.assertEqual(token_res.status_code, 200, token_res.content)
        token_payload = token_res.json()
        access_token = token_payload["access_token"]

        # 4. Misago fetches user profile at /accounts/oauth/userinfo/
        info_res = self.client.get(
            reverse("oauth_userinfo"),
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(info_res.status_code, 200, info_res.content)
        self.assertEqual(
            info_res.json(),
            {
                "id": str(self.user.pk),
                "sub": str(self.user.pk),
                "username": "enigma-agent",
                "name": "enigma-agent",
                "email": "agent@example.org",
                "email_verified": True,
                "participant_status": "approved",
                "is_collaborator": True,
                "is_staff": False,
            },
        )

    def test_userinfo_rejects_missing_scope_client_only_token_and_inactive_user(self):
        # Token lacking 'read' scope is rejected (403)
        write_only = AccessToken.objects.create(
            user=self.user,
            application=self.app,
            token="write-only-token",
            scope="write",
            expires=timezone.now() + timedelta(minutes=10),
        )
        self.assertEqual(
            self.client.get(
                reverse("oauth_userinfo"),
                HTTP_AUTHORIZATION=f"Bearer {write_only.token}",
            ).status_code,
            403,
        )

        # Client-credentials token without resource_owner returns 401
        machine_token = AccessToken.objects.create(
            user=None,
            application=self.app,
            token="machine-only-token",
            scope="read",
            expires=timezone.now() + timedelta(minutes=10),
        )
        self.assertEqual(
            self.client.get(
                reverse("oauth_userinfo"),
                HTTP_AUTHORIZATION=f"Bearer {machine_token.token}",
            ).status_code,
            401,
        )

        # Deactivated user is rejected cleanly
        valid_token = AccessToken.objects.create(
            user=self.user,
            application=self.app,
            token="valid-then-inactive-token",
            scope="read",
            expires=timezone.now() + timedelta(minutes=10),
        )
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        res = self.client.get(
            reverse("oauth_userinfo"),
            HTTP_AUTHORIZATION=f"Bearer {valid_token.token}",
        )
        self.assertIn(res.status_code, (401, 403))
