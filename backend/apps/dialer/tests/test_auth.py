"""
Tests for the JWT authentication system.

Covers login, token refresh, /me endpoint, logout, and the
JWTAuthenticationMiddleware (auth-exempt paths vs protected paths).
"""

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
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
        """POST with valid username/password returns 200 with user in body and auth cookies."""
        response = self.client.post(
            self.url,
            data=json.dumps({"username": "testuser", "password": self.password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "testuser")

        # Tokens should be in HttpOnly cookies, not in JSON body
        self.assertNotIn("access", data)
        self.assertNotIn("refresh", data)
        self.assertIn(settings.AUTH_ACCESS_COOKIE, response.cookies)
        self.assertIn(settings.AUTH_REFRESH_COOKIE, response.cookies)

        # Verify cookie flags
        access_cookie = response.cookies[settings.AUTH_ACCESS_COOKIE]
        self.assertTrue(access_cookie["httponly"])
        self.assertEqual(access_cookie["samesite"], "Lax")

    def test_login_invalid_credentials(self):
        """POST with wrong password returns 401."""
        response = self.client.post(
            self.url,
            data=json.dumps({"username": "testuser", "password": "wrongpass"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_login_user_without_usable_password(self):
        """POST with a user that has no usable password returns a clear message."""
        user = User.objects.create_user(username="nopassword", password=None)
        user.set_unusable_password()
        user.save(update_fields=["password"])

        response = self.client.post(
            self.url,
            data=json.dumps({"username": "nopassword", "password": "anypass"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json().get("detail"),
            "Password is not set for this account.",
        )

    def test_login_inactive_user(self):
        """POST with an inactive user returns a clear message."""
        inactive = User.objects.create_user(
            username="inactiveuser",
            password="inactivepass123",
            is_active=False,
        )
        inactive.save(update_fields=["is_active"])

        response = self.client.post(
            self.url,
            data=json.dumps(
                {"username": "inactiveuser", "password": "inactivepass123"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("detail"), "Account is inactive.")

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

    def test_refresh_via_cookie(self):
        """POST with refresh token in cookie returns 200 and updates access cookie."""
        refresh = RefreshToken.for_user(self.user)
        self.client.cookies[settings.AUTH_REFRESH_COOKIE] = str(refresh)

        response = self.client.post(
            self.url,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.AUTH_ACCESS_COOKIE, response.cookies)

    def test_refresh_via_body_fallback(self):
        """POST with refresh token in body (backwards compat) returns 200."""
        refresh = RefreshToken.for_user(self.user)
        response = self.client.post(
            self.url,
            data=json.dumps({"refresh": str(refresh)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_refresh_invalid_token(self):
        """POST with a garbage refresh token returns 401."""
        self.client.cookies[settings.AUTH_REFRESH_COOKIE] = "this-is-not-a-real-token"
        response = self.client.post(
            self.url,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)


class LogoutViewTests(TestCase):
    """Tests for POST /api/v1/dialer/auth/logout/"""

    def setUp(self):
        self.client = Client()
        self.url = "/api/v1/dialer/auth/logout/"
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_logout_clears_cookies(self):
        """POST to logout clears auth cookies."""
        # Login first to get cookies
        login_response = self.client.post(
            "/api/v1/dialer/auth/login/",
            data=json.dumps({"username": "testuser", "password": "testpass123"}),
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(self.url, content_type="application/json")
        self.assertEqual(response.status_code, 200)

        # Cookies should be deleted (max-age=0)
        access_cookie = response.cookies.get(settings.AUTH_ACCESS_COOKIE)
        if access_cookie:
            self.assertEqual(access_cookie["max-age"], 0)


@override_settings(AUTH_ENFORCEMENT_ENABLED=True)
class MeViewTests(TestCase):
    """Tests for GET /api/v1/dialer/auth/me/"""

    def setUp(self):
        self.client = Client()
        self.url = "/api/v1/dialer/auth/me/"
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_me_with_cookie(self):
        """GET /me/ with access token cookie returns 200 with user data."""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        self.client.cookies[settings.AUTH_ACCESS_COOKIE] = access_token

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "testuser")

    def test_me_with_header_fallback(self):
        """GET /me/ with Authorization header still works."""
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


@override_settings(AUTH_ENFORCEMENT_ENABLED=True)
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

    def test_protected_endpoint_with_cookie(self):
        """GET to /api/v1/dialer/agents/ with access token cookie does NOT return 401."""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        self.client.cookies[settings.AUTH_ACCESS_COOKIE] = access_token

        response = self.client.get("/api/v1/dialer/agents/")
        self.assertNotEqual(response.status_code, 401)

    def test_protected_endpoint_with_header(self):
        """GET to /api/v1/dialer/agents/ with Authorization header does NOT return 401."""
        refresh = RefreshToken.for_user(self.user)
        access_token = str(refresh.access_token)
        response = self.client.get(
            "/api/v1/dialer/agents/",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
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
        self.assertNotEqual(response.status_code, 401)
