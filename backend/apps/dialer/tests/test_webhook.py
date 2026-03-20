"""
Tests for Exotel webhook signature verification.

The ``verify_exotel_webhook`` decorator checks HMAC-SHA256 signatures and
shared-secret token query params when ``EXOTEL_WEBHOOK_SECRET`` is set.
"""

import hashlib
import hmac
import json
import os
from unittest.mock import patch

from django.test import Client, TestCase


class ExotelWebhookAuthTests(TestCase):
    """Tests for webhook authentication via the verify_exotel_webhook decorator.

    The webhook endpoint is at POST /api/v1/dialer/webhooks/exotel/.
    These tests focus on whether requests are rejected with 403 (auth failure)
    vs allowed through (non-403).  The webhook handler itself may produce
    other status codes (e.g. 200, 400, 500) depending on the request body,
    but a 403 specifically means the signature check failed.
    """

    WEBHOOK_URL = "/api/v1/dialer/webhooks/exotel/"

    def setUp(self):
        self.client = Client()
        self.body_dict = {"CallSid": "test-call-123", "EventType": "terminal"}
        self.body_bytes = json.dumps(self.body_dict).encode("utf-8")

    # ------------------------------------------------------------------
    # 1. No secret configured — decorator is a no-op
    # ------------------------------------------------------------------

    @patch.dict(os.environ, {"EXOTEL_WEBHOOK_SECRET": ""}, clear=False)
    def test_webhook_no_secret_configured(self):
        """When EXOTEL_WEBHOOK_SECRET is empty, the webhook should pass through (not 403)."""
        response = self.client.post(
            self.WEBHOOK_URL,
            data=self.body_bytes,
            content_type="application/json",
        )
        self.assertNotEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 2. Valid HMAC signature in header
    # ------------------------------------------------------------------

    @patch.dict(os.environ, {"EXOTEL_WEBHOOK_SECRET": "my-test-secret"}, clear=False)
    def test_webhook_valid_hmac_signature(self):
        """Correct HMAC-SHA256 signature in X-Exotel-Signature header passes verification."""
        secret = "my-test-secret"
        signature = hmac.new(
            secret.encode("utf-8"),
            self.body_bytes,
            hashlib.sha256,
        ).hexdigest()

        response = self.client.post(
            self.WEBHOOK_URL,
            data=self.body_bytes,
            content_type="application/json",
            HTTP_X_EXOTEL_SIGNATURE=signature,
        )
        self.assertNotEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 3. Invalid HMAC signature in header
    # ------------------------------------------------------------------

    @patch.dict(os.environ, {"EXOTEL_WEBHOOK_SECRET": "my-test-secret"}, clear=False)
    def test_webhook_invalid_hmac_signature(self):
        """Wrong HMAC signature returns 403."""
        response = self.client.post(
            self.WEBHOOK_URL,
            data=self.body_bytes,
            content_type="application/json",
            HTTP_X_EXOTEL_SIGNATURE="bad-signature-value",
        )
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 4. Valid token query parameter
    # ------------------------------------------------------------------

    @patch.dict(os.environ, {"EXOTEL_WEBHOOK_SECRET": "my-test-secret"}, clear=False)
    def test_webhook_valid_token_param(self):
        """Correct ?token= query param passes verification."""
        response = self.client.post(
            self.WEBHOOK_URL + "?token=my-test-secret",
            data=self.body_bytes,
            content_type="application/json",
        )
        self.assertNotEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 5. Invalid token query parameter
    # ------------------------------------------------------------------

    @patch.dict(os.environ, {"EXOTEL_WEBHOOK_SECRET": "my-test-secret"}, clear=False)
    def test_webhook_invalid_token_param(self):
        """Wrong ?token= query param returns 403."""
        response = self.client.post(
            self.WEBHOOK_URL + "?token=wrong-secret",
            data=self.body_bytes,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 6. No credentials at all when secret is required
    # ------------------------------------------------------------------

    @patch.dict(os.environ, {"EXOTEL_WEBHOOK_SECRET": "my-test-secret"}, clear=False)
    def test_webhook_no_credentials_when_secret_set(self):
        """No signature header and no token param when secret is configured returns 403."""
        response = self.client.post(
            self.WEBHOOK_URL,
            data=self.body_bytes,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
