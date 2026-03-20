"""
Shared call-related utility functions extracted from views.py.

These helpers are used by both the main dialer views and the HubSpot
service module, so they live here to avoid circular imports.
"""

from __future__ import annotations

import re

from ..models import CallSession, CallStatus


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def _status_to_log_status(status: str) -> str:
    value = (status or "").strip().lower()
    if value in {CallStatus.BRIDGED, CallStatus.HUMAN_DETECTED}:
        return "answered"
    if value == CallStatus.MACHINE_DETECTED:
        return "no-answer"
    if value == CallStatus.FAILED:
        return "failed"
    if value == CallStatus.COMPLETED:
        return "completed"
    if value in {CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING}:
        return "initiated"
    return value or "initiated"


def _flatten_payload_text(payload: object) -> list[str]:
    values: list[str] = []

    def _walk(item: object) -> None:
        if isinstance(item, dict):
            for value in item.values():
                _walk(value)
        elif isinstance(item, list):
            for value in item:
                _walk(value)
        elif item is not None:
            text = str(item).strip().lower()
            if text:
                values.append(text)

    _walk(payload)
    return values


def _extract_event_type(raw_payload: dict) -> str:
    if not isinstance(raw_payload, dict):
        return ""

    last_event = raw_payload.get("last_event")
    if isinstance(last_event, dict):
        value = (
            last_event.get("EventType")
            or last_event.get("CallStatus")
            or last_event.get("Status")
            or last_event.get("event")
            or ""
        )
        return str(value).strip().lower()

    events = raw_payload.get("events")
    if isinstance(events, list) and events:
        event = events[-1]
        if isinstance(event, dict):
            value = event.get("EventType") or event.get("CallStatus") or event.get("Status") or ""
            return str(value).strip().lower()

    return ""


def _extract_provider_disposition(raw_payload: dict) -> str:
    tokens = _flatten_payload_text(raw_payload)
    if not tokens:
        return ""

    def has_any(keywords: tuple[str, ...]) -> bool:
        return any(any(keyword in token for keyword in keywords) for token in tokens)

    # Keep specific outcomes first; payloads often include generic words like terminal/completed too.
    if has_any(("busy",)):
        return "busy"
    if has_any(("no-answer", "no_answer", "noanswer", "not answered", "unanswered", "timeout")):
        return "no-answer"
    if has_any(("cancelled", "canceled", "cancel")):
        return "cancelled"
    if has_any(("failed", "failure", "error", "rejected", "unreachable")):
        return "failed"
    if has_any(("answered", "connected", "in-progress", "inprogress", "human_detected", "human")):
        return "answered"
    if has_any(("completed", "terminal", "hangup", "disconnected")):
        return "completed"
    return ""


def _is_duration_eligible_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"answered", "completed"}


def _coerce_duration_seconds(value: object) -> int | None:
    max_reasonable_seconds = 12 * 60 * 60

    if value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = max(0, int(value))
        return parsed if parsed <= max_reasonable_seconds else None

    text = str(value).strip()
    if not text:
        return None

    # Ignore datetime-like strings (e.g. 2026-03-04 14:49:22) that are not durations.
    if ("-" in text and ":" in text) or "t" in text.lower():
        return None

    if text.isdigit():
        parsed = max(0, int(text))
        return parsed if parsed <= max_reasonable_seconds else None

    if ":" in text:
        parts = text.split(":")
        if all(part.isdigit() for part in parts):
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                if seconds >= 60:
                    return None
                parsed = max(0, minutes * 60 + seconds)
                return parsed if parsed <= max_reasonable_seconds else None
            if len(parts) == 3:
                hours, minutes, seconds = map(int, parts)
                if minutes >= 60 or seconds >= 60:
                    return None
                parsed = max(0, hours * 3600 + minutes * 60 + seconds)
                return parsed if parsed <= max_reasonable_seconds else None

    match = re.fullmatch(r"(\d+)\s*(s|sec|secs|second|seconds)?", text.lower())
    if match:
        parsed = max(0, int(match.group(1)))
        return parsed if parsed <= max_reasonable_seconds else None
    return None


def _extract_talk_duration_seconds(raw_payload: dict) -> int | None:
    preferred_keys = (
        "ConversationDuration",
        "TalkTime",
        "talk_time",
        "BillSec",
        "billsec",
        "conversation_duration",
        "talk_duration",
        "bill_sec",
    )

    def scan(obj: object) -> int | None:
        if isinstance(obj, dict):
            for key in preferred_keys:
                if key in obj:
                    parsed = _coerce_duration_seconds(obj.get(key))
                    if parsed is not None:
                        return parsed

            for key, value in obj.items():
                key_text = str(key).lower()
                if ("talk" in key_text or "billsec" in key_text or "conversation" in key_text) and "recording" not in key_text:
                    parsed = _coerce_duration_seconds(value)
                    if parsed is not None:
                        return parsed

            for value in obj.values():
                # Recurse only into nested containers; avoid parsing arbitrary scalar fields.
                if not isinstance(value, (dict, list)):
                    continue
                parsed = scan(value)
                if parsed is not None:
                    return parsed
            return None

        if isinstance(obj, list):
            for item in reversed(obj):
                if not isinstance(item, (dict, list)):
                    continue
                parsed = scan(item)
                if parsed is not None:
                    return parsed
            return None

        return None

    for source in (
        raw_payload.get("last_event"),
        raw_payload.get("events"),
        raw_payload.get("init_response"),
        raw_payload.get("exotel_poll"),
        raw_payload.get("exotel_poll", {}).get("call") if isinstance(raw_payload.get("exotel_poll"), dict) else None,
        raw_payload.get("exotel_poll", {}).get("raw") if isinstance(raw_payload.get("exotel_poll"), dict) else None,
    ):
        parsed = scan(source)
        if parsed is not None:
            return parsed

    return None


# ---------------------------------------------------------------------------
# Composite helpers
# ---------------------------------------------------------------------------


def _derive_display_status(call: CallSession) -> str:
    base_status = _status_to_log_status(call.status)
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}

    event_type = _extract_event_type(raw_payload)
    payload_disposition = _extract_provider_disposition(raw_payload)

    manual_hangup_requested = isinstance(raw_payload.get("manual_hangup_requested"), dict)
    provider_negative_disposition = payload_disposition in {"busy", "no-answer", "cancelled", "failed"}
    event_negative_disposition = bool(
        event_type
        and any(token in event_type for token in ("busy", "no-answer", "no_answer", "cancelled", "canceled", "failed"))
    )
    connected_event = bool(event_type and any(token in event_type for token in ("answered", "connected", "in-progress", "inprogress")))
    was_connected = bool(call.answered_at) or base_status == "answered" or payload_disposition == "answered" or connected_event

    if manual_hangup_requested and was_connected and not provider_negative_disposition and not event_negative_disposition:
        return "sdr-cut"

    if payload_disposition:
        return payload_disposition

    if event_type:
        if any(token in event_type for token in ("busy",)):
            return "busy"
        if any(token in event_type for token in ("no-answer", "no_answer", "noanswer")):
            return "no-answer"
        if any(token in event_type for token in ("cancelled", "canceled")):
            return "cancelled"
        if any(token in event_type for token in ("answered", "connected", "in-progress", "inprogress")):
            return "answered"
        if any(token in event_type for token in ("failed",)):
            return "failed"
        if any(token in event_type for token in ("completed", "terminal", "hangup", "disconnected")):
            return "completed"

    return base_status


def _duration_seconds_for_call(call: CallSession) -> int | None:
    display_status = _derive_display_status(call)
    if not _is_duration_eligible_status(display_status):
        return None

    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    duration_seconds = _extract_talk_duration_seconds(raw_payload)
    if duration_seconds is not None and duration_seconds >= 0:
        return int(duration_seconds)

    if call.answered_at and call.ended_at and call.ended_at >= call.answered_at:
        return max(0, int((call.ended_at - call.answered_at).total_seconds()))

    # Exotel may omit explicit answer/talk fields even for successful calls.
    # In that case, show a conservative fallback based on provider call leg timing.
    start_at = call.started_at or call.created_at
    end_at = call.ended_at
    if start_at and end_at and end_at >= start_at:
        return max(0, int((end_at - start_at).total_seconds()))

    return None
