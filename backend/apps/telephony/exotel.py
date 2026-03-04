import json
import os
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .base import DialRequest, DialResponse, TelephonyProvider, WebhookEvent


class ExotelProvider(TelephonyProvider):
    def __init__(self) -> None:
        self.account_sid = os.getenv("EXOTEL_SID", "").strip()
        self.api_key = os.getenv("EXOTEL_API_KEY", "").strip()
        self.api_token = os.getenv("EXOTEL_API_TOKEN", "").strip()
        self.subdomain = os.getenv("EXOTEL_SUBDOMAIN", "").replace("@", "").strip()
        self.default_caller_id = os.getenv("EXOTEL_CALLER_ID", "").strip()
        self.timeout_seconds = float(os.getenv("EXOTEL_TIMEOUT_SECONDS", "10"))

    @property
    def configured(self) -> bool:
        return bool(self.account_sid and self.api_key and self.api_token and self.subdomain)

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}/v1/Accounts/{self.account_sid}"

    def _auth(self) -> HTTPBasicAuth:
        return HTTPBasicAuth(self.api_key, self.api_token)

    def initiate_call(self, request: DialRequest) -> DialResponse:
        if not self.configured:
            return DialResponse(provider_call_id="", accepted=False, raw={"error": "missing_exotel_configuration"})

        caller_id = request.caller_id or self.default_caller_id
        if not caller_id:
            return DialResponse(provider_call_id="", accepted=False, raw={"error": "missing_caller_id"})

        payload: list[tuple[str, str]] = [
            ("From", request.from_number),
            ("To", request.to_number),
            ("CallerId", caller_id),
        ]

        if request.callback_url:
            payload.extend(
                [
                    ("StatusCallback", request.callback_url),
                    ("StatusCallbackContentType", "application/json"),
                    ("StatusCallbackEvents[]", "answered"),
                    ("StatusCallbackEvents[]", "terminal"),
                ]
            )

        if request.metadata:
            payload.append(("CustomField", json.dumps(request.metadata)))

        if request.max_duration_seconds and request.max_duration_seconds > 0:
            payload.append(("TimeLimit", str(int(request.max_duration_seconds))))

        endpoint = f"{self.base_url}/Calls/connect.json"
        try:
            response = requests.post(
                endpoint,
                data=payload,
                auth=self._auth(),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            return DialResponse(provider_call_id="", accepted=False, raw={"error": str(exc)})

        try:
            raw_payload: Any = response.json()
        except ValueError:
            raw_payload = {"raw_text": response.text}

        if response.status_code >= 400:
            return DialResponse(
                provider_call_id="",
                accepted=False,
                raw={"http_status": response.status_code, "provider_response": raw_payload},
            )

        provider_call_id = ""
        if isinstance(raw_payload, dict):
            call_data = raw_payload.get("Call", {})
            if isinstance(call_data, dict):
                provider_call_id = str(call_data.get("Sid", ""))
            if not provider_call_id:
                provider_call_id = str(raw_payload.get("Sid", ""))

        return DialResponse(
            provider_call_id=provider_call_id,
            accepted=bool(provider_call_id),
            raw=raw_payload if isinstance(raw_payload, dict) else {"provider_response": raw_payload},
        )

    def parse_webhook(self, payload: dict) -> WebhookEvent:
        provider_call_id = str(payload.get("CallSid") or payload.get("Sid") or "")
        call_data = payload.get("Call")
        if not provider_call_id and isinstance(call_data, dict):
            provider_call_id = str(call_data.get("Sid") or "")

        event_type = str(payload.get("EventType") or payload.get("CallStatus") or payload.get("Status") or "unknown")

        amd_result = str(self._extract_answered_by(payload) or "").strip() or None

        return WebhookEvent(
            provider_call_id=provider_call_id,
            event_type=event_type,
            amd_result=amd_result,
            raw=payload,
        )

    def hangup(self, provider_call_id: str) -> None:
        if not self.configured or not provider_call_id:
            return

        endpoint = f"{self.base_url}/Calls/{provider_call_id}.json"
        try:
            requests.post(
                endpoint,
                data={"Status": "completed"},
                auth=self._auth(),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            return

    def fetch_call(self, provider_call_id: str) -> dict:
        if not self.configured or not provider_call_id:
            return {"ok": False, "error": "missing_configuration_or_call_id"}

        endpoint = f"{self.base_url}/Calls/{provider_call_id}.json"
        try:
            response = requests.get(
                endpoint,
                auth=self._auth(),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            return {"ok": False, "error": str(exc)}

        try:
            raw_payload: Any = response.json()
        except ValueError:
            raw_payload = {"raw_text": response.text}

        if response.status_code >= 400:
            return {
                "ok": False,
                "error": "provider_http_error",
                "http_status": response.status_code,
                "raw": raw_payload,
            }

        call_data = raw_payload.get("Call") if isinstance(raw_payload, dict) else None
        if not isinstance(call_data, dict):
            call_data = raw_payload if isinstance(raw_payload, dict) else {}

        return {"ok": True, "call": call_data, "raw": raw_payload}

    def _extract_answered_by(self, payload: dict) -> str | None:
        if "AnsweredBy" in payload:
            return str(payload.get("AnsweredBy"))

        for key, value in payload.items():
            if "AnsweredBy" in str(key):
                return str(value)

        legs = payload.get("Legs")
        if isinstance(legs, dict):
            for leg_data in legs.values():
                if isinstance(leg_data, dict) and "AnsweredBy" in leg_data:
                    return str(leg_data.get("AnsweredBy"))

        return None
