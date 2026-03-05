import json
import logging
import os
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .base import DialRequest, DialResponse, TelephonyProvider, WebhookEvent

logger = logging.getLogger("dialer.exotel")


def _debug_exotel(tag: str, payload: Any) -> None:
    try:
        text = json.dumps(payload, default=str)
    except Exception:
        text = str(payload)
    print(f"[EXOTEL_DEBUG] {tag}: {text}", flush=True)
    logger.info("EXOTEL_DEBUG %s %s", tag, text)


class ExotelProvider(TelephonyProvider):
    def __init__(self) -> None:
        self.account_sid = os.getenv("EXOTEL_SID", "").strip()
        self.api_key = os.getenv("EXOTEL_API_KEY", "").strip()
        self.api_token = os.getenv("EXOTEL_API_TOKEN", "").strip()
        self.subdomain = os.getenv("EXOTEL_SUBDOMAIN", "").replace("@", "").strip()
        self.default_caller_id = os.getenv("EXOTEL_CALLER_ID", "").strip()
        self.timeout_seconds = float(os.getenv("EXOTEL_TIMEOUT_SECONDS", "10"))
        self.wait_url = os.getenv("EXOTEL_WAIT_URL", "").strip()
        self.start_playback_value = os.getenv("EXOTEL_START_PLAYBACK_VALUE", "").strip()
        self.start_playback_to = os.getenv("EXOTEL_START_PLAYBACK_TO", "").strip().lower()

    @property
    def configured(self) -> bool:
        return bool(self.account_sid and self.api_key and self.api_token and self.subdomain)

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}/v1/Accounts/{self.account_sid}"

    def _auth(self) -> HTTPBasicAuth:
        return HTTPBasicAuth(self.api_key, self.api_token)

    @staticmethod
    def _is_start_playback_error(http_status: int, raw_payload: Any) -> bool:
        if int(http_status or 0) != 400 or not isinstance(raw_payload, dict):
            return False
        rest_error = raw_payload.get("RestException")
        if not isinstance(rest_error, dict):
            return False
        message = str(rest_error.get("Message") or "").strip().lower()
        if not message:
            return False
        return "startplaybackvalue" in message or "start playback" in message

    def _normalize_provider_url(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith(("http://", "https://")):
            return text
        if text.startswith("//"):
            return f"https:{text}"
        if text.startswith("/"):
            return f"https://{self.subdomain}{text}"
        if text.startswith("v1/"):
            return f"https://{self.subdomain}/{text}"
        if text.startswith(self.subdomain):
            return f"https://{text}"
        return ""

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

        # Waiting audio while Exotel connects the second leg.
        if self.wait_url:
            payload.append(("WaitUrl", self.wait_url))

        # Optional pre-connect audio playback (e.g., "Please wait while we connect you").
        # Value is typically an audio URL supported by Exotel.
        start_playback_enabled = False
        if self.start_playback_value:
            payload.append(("StartPlaybackValue", self.start_playback_value))
            if self.start_playback_to in {"callee", "both"}:
                payload.append(("StartPlaybackTo", "Both" if self.start_playback_to == "both" else "Callee"))
            start_playback_enabled = True

        # Enable recording by default unless explicitly disabled via env.
        record_calls_raw = str(os.getenv("EXOTEL_RECORD_CALLS", "1")).strip().lower()
        record_calls = record_calls_raw in {"1", "true", "yes", "on"}
        if record_calls:
            payload.append(("Record", "true"))

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
        _debug_exotel(
            "initiate_call_request",
            {
                "endpoint": endpoint,
                "from_number": request.from_number,
                "to_number": request.to_number,
                "caller_id": caller_id,
                "callback_url": request.callback_url,
                "metadata": request.metadata or {},
                "max_duration_seconds": request.max_duration_seconds,
                "wait_url_enabled": bool(self.wait_url),
                "wait_url": self.wait_url or None,
                "start_playback_enabled": bool(self.start_playback_value),
                "start_playback_to": self.start_playback_to or None,
                "payload": payload,
            },
        )
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

        _debug_exotel(
            "initiate_call_response",
            {
                "endpoint": endpoint,
                "status_code": response.status_code,
                "raw_payload": raw_payload,
            },
        )

        if start_playback_enabled and self._is_start_playback_error(response.status_code, raw_payload):
            retry_payload = [
                pair
                for pair in payload
                if pair[0] not in {"StartPlaybackValue", "StartPlaybackTo"}
            ]
            _debug_exotel(
                "initiate_call_retry_without_start_playback",
                {
                    "endpoint": endpoint,
                    "reason": "start_playback_rejected",
                    "status_code": response.status_code,
                },
            )
            try:
                response = requests.post(
                    endpoint,
                    data=retry_payload,
                    auth=self._auth(),
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                return DialResponse(provider_call_id="", accepted=False, raw={"error": str(exc)})

            try:
                raw_payload = response.json()
            except ValueError:
                raw_payload = {"raw_text": response.text}

            _debug_exotel(
                "initiate_call_retry_response",
                {
                    "endpoint": endpoint,
                    "status_code": response.status_code,
                    "raw_payload": raw_payload,
                },
            )

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
        _debug_exotel("webhook_payload", payload)

        provider_call_id = str(payload.get("CallSid") or payload.get("Sid") or "")
        call_data = payload.get("Call")
        if not provider_call_id and isinstance(call_data, dict):
            provider_call_id = str(
                call_data.get("Sid")
                or call_data.get("CallSid")
                or call_data.get("UUID")
                or call_data.get("CallUUID")
                or call_data.get("id")
                or ""
            )

        event_type = str(
            payload.get("EventType")
            or payload.get("CallStatus")
            or payload.get("Status")
            or (call_data.get("EventType") if isinstance(call_data, dict) else "")
            or (call_data.get("CallStatus") if isinstance(call_data, dict) else "")
            or (call_data.get("Status") if isinstance(call_data, dict) else "")
            or "unknown"
        )

        amd_result = str(self._extract_answered_by(payload) or "").strip() or None

        _debug_exotel(
            "webhook_parsed_event",
            {
                "provider_call_id": provider_call_id,
                "event_type": event_type,
                "amd_result": amd_result,
            },
        )

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
        _debug_exotel(
            "fetch_call_request",
            {
                "endpoint": endpoint,
                "provider_call_id": provider_call_id,
            },
        )
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

        _debug_exotel(
            "fetch_call_response",
            {
                "endpoint": endpoint,
                "provider_call_id": provider_call_id,
                "status_code": response.status_code,
                "raw_payload": raw_payload,
            },
        )

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

    def fetch_call_recording(self, provider_call_id: str) -> dict:
        if not self.configured or not provider_call_id:
            return {"ok": False, "error": "missing_configuration_or_call_id"}

        endpoints: list[str] = self._recording_endpoints_for_call(provider_call_id)
        # In some Exotel flows recordings are attached to ParentCallSid.
        parent_sid = ""
        call_fetch = self.fetch_call(provider_call_id)
        if call_fetch.get("ok") and isinstance(call_fetch.get("call"), dict):
            parent_sid = str(call_fetch.get("call", {}).get("ParentCallSid") or "").strip()
        if parent_sid and parent_sid != provider_call_id:
            for endpoint in self._recording_endpoints_for_call(parent_sid):
                if endpoint not in endpoints:
                    endpoints.append(endpoint)
        attempts: list[dict] = []

        for endpoint in endpoints:
            _debug_exotel(
                "fetch_call_recording_request",
                {
                    "endpoint": endpoint,
                    "provider_call_id": provider_call_id,
                },
            )
            try:
                response = requests.get(
                    endpoint,
                    auth=self._auth(),
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                attempts.append({"endpoint": endpoint, "error": str(exc)})
                continue

            try:
                raw_payload: Any = response.json()
            except ValueError:
                raw_payload = {"raw_text": response.text}

            _debug_exotel(
                "fetch_call_recording_response",
                {
                    "endpoint": endpoint,
                    "provider_call_id": provider_call_id,
                    "status_code": response.status_code,
                    "raw_payload": raw_payload,
                },
            )

            attempts.append({"endpoint": endpoint, "status_code": response.status_code})
            if response.status_code >= 400:
                continue

            recording_url = self._extract_recording_url(raw_payload)
            if recording_url:
                return {
                    "ok": True,
                    "recording_url": recording_url,
                    "endpoint": endpoint,
                    "raw": raw_payload if isinstance(raw_payload, dict) else {"provider_response": raw_payload},
                }

        return {"ok": False, "error": "recording_not_found", "attempts": attempts[:10]}

    def _recording_endpoints_for_call(self, call_sid: str) -> list[str]:
        call_sid = str(call_sid or "").strip()
        if not call_sid:
            return []
        return [
            f"{self.base_url}/Calls/{call_sid}/recordings.json",
            f"{self.base_url}/Calls/{call_sid}/Recordings.json",
            f"{self.base_url}/Calls/{call_sid}/Recording.json",
            f"{self.base_url}/Calls/{call_sid}.json?include_recordings=true",
        ]

    def _extract_recording_url(self, payload: object) -> str:
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_text = str(key).lower()
                if isinstance(value, str):
                    text = value.strip()
                    if "record" in key_text or any(ext in text.lower() for ext in (".mp3", ".wav")) or "/record" in text.lower():
                        normalized = self._normalize_provider_url(text)
                        if normalized:
                            return normalized
                nested = self._extract_recording_url(value)
                if nested:
                    return nested
            return ""
        if isinstance(payload, list):
            for item in payload:
                nested = self._extract_recording_url(item)
                if nested:
                    return nested
            return ""
        return ""

    def _extract_answered_by(self, payload: dict) -> str | None:
        if "AnsweredBy" in payload:
            return str(payload.get("AnsweredBy"))

        call_data = payload.get("Call")
        if isinstance(call_data, dict) and "AnsweredBy" in call_data:
            return str(call_data.get("AnsweredBy"))

        for key, value in payload.items():
            if "AnsweredBy" in str(key):
                return str(value)

        legs = payload.get("Legs")
        if isinstance(legs, dict):
            for leg_data in legs.values():
                if isinstance(leg_data, dict) and "AnsweredBy" in leg_data:
                    return str(leg_data.get("AnsweredBy"))

        return None
