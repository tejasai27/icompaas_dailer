"""
Unit tests for HubSpot service helper functions.

These tests exercise pure utility functions and mock external HTTP calls
so they do not require any network connectivity or HubSpot credentials.
"""

from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase

from apps.dialer.services.hubspot_service import (
    _first_non_empty_text,
    _hubspot_api_request,
    _map_hubspot_call_status,
    _mask_secret,
    _normalize_hubspot_deal_id,
)


# ---------------------------------------------------------------------------
# _normalize_hubspot_deal_id
# ---------------------------------------------------------------------------


class NormalizeHubspotDealIdTests(SimpleTestCase):
    """Tests for _normalize_hubspot_deal_id."""

    def test_normalize_hubspot_deal_id_numeric(self):
        """Plain numeric string '12345' is returned unchanged."""
        self.assertEqual(_normalize_hubspot_deal_id("12345"), "12345")

    def test_normalize_hubspot_deal_id_float(self):
        """Float-like '12345.0' is normalised to '12345'."""
        self.assertEqual(_normalize_hubspot_deal_id("12345.0"), "12345")

    def test_normalize_hubspot_deal_id_empty(self):
        """Empty string returns empty string."""
        self.assertEqual(_normalize_hubspot_deal_id(""), "")

    def test_normalize_hubspot_deal_id_none(self):
        """None is treated as empty."""
        self.assertEqual(_normalize_hubspot_deal_id(None), "")

    def test_normalize_hubspot_deal_id_non_numeric(self):
        """Non-numeric text is returned as-is."""
        self.assertEqual(_normalize_hubspot_deal_id("abc-deal"), "abc-deal")

    def test_normalize_hubspot_deal_id_float_trailing_zeros(self):
        """'99.000' is normalised to '99'."""
        self.assertEqual(_normalize_hubspot_deal_id("99.000"), "99")


# ---------------------------------------------------------------------------
# _first_non_empty_text
# ---------------------------------------------------------------------------


class FirstNonEmptyTextTests(SimpleTestCase):
    """Tests for _first_non_empty_text."""

    def test_first_non_empty_text_basic(self):
        """Returns the first non-empty string."""
        self.assertEqual(_first_non_empty_text("", "hello", "world"), "hello")

    def test_first_non_empty_text_all_empty(self):
        """Returns empty string when all values are empty or None."""
        self.assertEqual(_first_non_empty_text("", None, "  "), "")

    def test_first_non_empty_text_first_value(self):
        """Returns the very first value when it is non-empty."""
        self.assertEqual(_first_non_empty_text("first", "second"), "first")

    def test_first_non_empty_text_none_skipped(self):
        """None values are skipped."""
        self.assertEqual(_first_non_empty_text(None, None, "value"), "value")

    def test_first_non_empty_text_no_args(self):
        """No arguments returns empty string."""
        self.assertEqual(_first_non_empty_text(), "")


# ---------------------------------------------------------------------------
# _mask_secret
# ---------------------------------------------------------------------------


class MaskSecretTests(SimpleTestCase):
    """Tests for _mask_secret."""

    def test_mask_secret_short(self):
        """Short strings (<=8 chars) are fully masked."""
        self.assertEqual(_mask_secret("abcd"), "****")
        self.assertEqual(_mask_secret("12345678"), "********")

    def test_mask_secret_long(self):
        """Long strings show first and last 4 chars with asterisks in between."""
        result = _mask_secret("abcdefghijklmnop")  # 16 chars
        self.assertEqual(result, "abcd********mnop")

    def test_mask_secret_empty(self):
        """Empty / None returns empty string."""
        self.assertEqual(_mask_secret(""), "")
        self.assertEqual(_mask_secret(None), "")


# ---------------------------------------------------------------------------
# _map_hubspot_call_status
# ---------------------------------------------------------------------------


class MapHubspotCallStatusTests(SimpleTestCase):
    """Tests for _map_hubspot_call_status."""

    def test_map_hubspot_call_status_completed(self):
        """A normal completed call maps to 'COMPLETED'."""
        self.assertEqual(_map_hubspot_call_status("completed", ""), "COMPLETED")

    def test_map_hubspot_call_status_failed(self):
        """A failed call maps to 'FAILED'."""
        self.assertEqual(_map_hubspot_call_status("failed", ""), "FAILED")

    def test_map_hubspot_call_status_no_answer(self):
        """A no-answer call maps to 'NO_ANSWER'."""
        self.assertEqual(_map_hubspot_call_status("no-answer", ""), "NO_ANSWER")

    def test_map_hubspot_call_status_busy(self):
        """A busy call maps to 'BUSY'."""
        self.assertEqual(_map_hubspot_call_status("busy", ""), "BUSY")

    def test_map_hubspot_call_status_sdr_cut(self):
        """SDR cut maps to 'FAILED'."""
        self.assertEqual(_map_hubspot_call_status("sdr-cut", ""), "FAILED")

    def test_map_hubspot_call_status_voicemail(self):
        """Machine/voicemail outcome maps to 'VOICEMAIL'."""
        self.assertEqual(_map_hubspot_call_status("", "voicemail"), "VOICEMAIL")


# ---------------------------------------------------------------------------
# _hubspot_api_request (mocked HTTP)
# ---------------------------------------------------------------------------


class HubspotApiRequestTests(SimpleTestCase):
    """Tests for _hubspot_api_request with mocked requests.request."""

    @patch("apps.dialer.services.hubspot_service.requests.request")
    def test_hubspot_api_request_success(self, mock_request):
        """A 200 response from HubSpot returns ok=True with the parsed JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "12345", "properties": {}}
        mock_request.return_value = mock_response

        result = _hubspot_api_request(
            access_token="fake-token",
            method="GET",
            path="/crm/v3/objects/calls/12345",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["raw"]["id"], "12345")
        self.assertEqual(result["error"], "")

    @patch("apps.dialer.services.hubspot_service.requests.request")
    def test_hubspot_api_request_failure(self, mock_request):
        """A 400 response from HubSpot returns ok=False with an error message."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Invalid input"}
        mock_request.return_value = mock_response

        result = _hubspot_api_request(
            access_token="fake-token",
            method="POST",
            path="/crm/v3/objects/calls",
            payload={"properties": {}},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["error"], "Invalid input")

    @patch("apps.dialer.services.hubspot_service.requests.request")
    def test_hubspot_api_request_timeout(self, mock_request):
        """A Timeout exception returns ok=False with status_code 0."""
        mock_request.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = _hubspot_api_request(
            access_token="fake-token",
            method="GET",
            path="/crm/v3/objects/calls/999",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 0)
        self.assertIn("timed out", result["error"].lower())
