"""
Tests for the JWT authentication system.

Covers login, token refresh, /me endpoint, and the JWTAuthenticationMiddleware
(auth-exempt paths vs protected paths).
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class LoginViewTests(TestCase):
    """Tests for POST /api/v1/dialer/auth/login/"""

    def setUp(self):
        self.client = Client()
        self.url = "/api/v1/dialer/auth/login/"
        self.password = "testpass123"
        self.user = User.objects.create_user(
            username="testuser",
            password=self.password,
        )

    def test_login_valid_credentials(self):
        """POST with valid username/password returns 200 with access, refresh, user keys."""
        response = self.client.post(
            self.url,
            data=json.dumps({"username": "testuser", "password": self.password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "testuser")

    def test_login_invalid_credentials(self):
        """POST with wrong password returns 401."""
        response = self.client.post(
            self.url,
            data=json.dumps({"username": "testuser", "password": "wrongpass"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_login_missing_fields(self):
        """POST with empty username/password returns 400."""
        response = self.client.post(
            self.url,
            data=json.dumps({"username": "", "password": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class RefreshViewTests(TestCase):
    """Tests for POST /api/v1/dialer/auth/refresh/"""

    def setUp(self):
        self.client = Client()
        self.url = "/api/v1/dialer/auth/refresh/"
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_refresh_valid_token(self):
        """POST with a valid refresh token returns 200 with a new access token."""
        refresh = RefreshToken.for_user(self.user)
        response = self.client.post(
            self.url,
            data=json.dumps({"refresh": str(refresh)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)
        self.assertTrue(len(data["access"]) > 0)

    def test_refresh_invalid_token(self):
        """POST with a garbage refresh token returns 401."""
        response = self.client.post(
            self.url,
            data=json.dumps({"refresh": "this-is-not-a-real-token"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)


class MeViewTests(TestCase):
    """Tests for GET /api/v1/dialer/auth/me/"""

    def setUp(self):
        self.client = Client()
        self.url = "/api/v1/dialer/auth/me/"
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_me_authenticated(self):
        """GET /me/ with a valid access token returns 200 with user data."""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        response = self.client.get(
            self.url,
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "testuser")


class JWTMiddlewareTests(TestCase):
    """Tests for JWTAuthenticationMiddleware — protected vs exempt paths."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_protected_endpoint_without_token(self):
        """GET to /api/v1/dialer/agents/ without a token returns 401."""
        response = self.client.get("/api/v1/dialer/agents/")
        self.assertEqual(response.status_code, 401)

    def test_protected_endpoint_with_token(self):
        """GET to /api/v1/dialer/agents/ with a valid token does NOT return 401."""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        response = self.client.get(
            "/api/v1/dialer/agents/",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        # The view itself may return any success/error code, but it must not
        # be a 401 since we provided a valid token.
        self.assertNotEqual(response.status_code, 401)

    def test_health_exempt_from_auth(self):
        """GET to /api/v1/dialer/health/ without a token should NOT return 401."""
        response = self.client.get("/api/v1/dialer/health/")
        self.assertNotEqual(response.status_code, 401)

    def test_webhook_exempt_from_auth(self):
        """POST to /api/v1/dialer/webhooks/exotel/ without a JWT should NOT return 401."""
        response = self.client.post(
            "/api/v1/dialer/webhooks/exotel/",
            data=json.dumps({"CallSid": "test123"}),
            content_type="application/json",
        )
        # The webhook endpoint is exempt from JWT auth, so we must NOT get 401.
        # It may return 403 (webhook signature failure) or other codes, but
        # never 401 from the JWT middleware.
        self.assertNotEqual(response.status_code, 401)
