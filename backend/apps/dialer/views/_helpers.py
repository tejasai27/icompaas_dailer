import json
import logging
import os
import re
from datetime import datetime
from urllib.parse import parse_qsl

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.telephony.exotel import ExotelProvider

from ..models import (
    CallSession,
    CallStatus,
)
from ..services.call_utils import (
    _derive_display_status,
    _duration_seconds_for_call,
    _is_duration_eligible_status,
    _parse_bool,
)

logger = logging.getLogger("dialer.campaign")

# ─── constants ──────────────────────────────────────────────────────
RUNTIME_EXOTEL_WAIT_AUDIO_CACHE_KEY = "dialer:runtime:exotel_wait_audio"
WAIT_AUDIO_ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}
WAIT_AUDIO_MAX_BYTES = int(os.getenv("EXOTEL_WAIT_AUDIO_MAX_BYTES", "5242880") or 5242880)
RECORDING_UPLOAD_ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}
RECORDING_UPLOAD_MAX_BYTES = int(os.getenv("RECORDING_UPLOAD_MAX_BYTES", "52428800") or 52428800)
AUTO_TRANSCRIBE_RECORDINGS = str(os.getenv("AUTO_TRANSCRIBE_RECORDINGS", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
AUTO_TRANSCRIBE_LOCK_SECONDS = max(60, int(os.getenv("AUTO_TRANSCRIBE_LOCK_SECONDS", "900") or 900))
AUTO_TRANSCRIBE_RETRY_FAILED_SECONDS = max(
    30,
    int(os.getenv("AUTO_TRANSCRIBE_RETRY_FAILED_SECONDS", "180") or 180),
)
AUTO_TRANSCRIBE_STALE_PROCESSING_SECONDS = max(
    120,
    int(os.getenv("AUTO_TRANSCRIBE_STALE_PROCESSING_SECONDS", "1200") or 1200),
)
AUTO_TRANSCRIBE_DOWNLOAD_RETRIES = max(0, int(os.getenv("AUTO_TRANSCRIBE_DOWNLOAD_RETRIES", "4") or 4))
AUTO_TRANSCRIBE_DOWNLOAD_RETRY_DELAY_SECONDS = max(
    3,
    int(os.getenv("AUTO_TRANSCRIBE_DOWNLOAD_RETRY_DELAY_SECONDS", "15") or 15),
)
TRANSCRIPTION_PROGRESS_CACHE_PREFIX = "dialer:recording:transcribe_progress:"
TRANSCRIPTION_PROGRESS_TTL_SECONDS = max(
    300,
    int(os.getenv("TRANSCRIPTION_PROGRESS_TTL_SECONDS", "14400") or 14400),
)
TRANSCRIPTION_ENGLISH_ONLY = str(os.getenv("TRANSCRIPTION_ENGLISH_ONLY", "1") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TRANSCRIPTION_NON_ENGLISH_ERROR = "unable to transcript different language detected"
TRANSCRIPTION_BACKEND = str(os.getenv("TRANSCRIPTION_BACKEND") or "local_whisper").strip().lower()
WHISPER_MODEL_NAME = str(os.getenv("WHISPER_MODEL") or "small").strip() or "small"
WHISPER_LANGUAGE = str(os.getenv("WHISPER_LANGUAGE") or "").strip()
WHISPER_DEVICE = str(os.getenv("WHISPER_DEVICE") or "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = str(os.getenv("WHISPER_COMPUTE_TYPE") or "int8").strip() or "int8"
WHISPER_BEAM_SIZE = max(1, int(os.getenv("WHISPER_BEAM_SIZE", "3") or 3))
WHISPER_VAD_FILTER = str(os.getenv("WHISPER_VAD_FILTER", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
WHISPER_CONDITION_ON_PREVIOUS_TEXT = str(os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
WHISPER_TEMPERATURE = float(os.getenv("WHISPER_TEMPERATURE", "0") or 0.0)
OPENAI_AUDIO_TRANSCRIPT_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


# ─── helper functions ───────────────────────────────────────────────
def _debug_runtime(tag: str, payload: object) -> None:
    try:
        text = json.dumps(payload, default=str)
    except Exception:
        text = str(payload)
    print(f"[EXOTEL_DEBUG] {tag}: {text}", flush=True)
    logger.info("EXOTEL_DEBUG %s %s", tag, text)


def _public_base_url_from_request(request: HttpRequest) -> str:
    configured_base = str(getattr(settings, "PUBLIC_WEBHOOK_BASE_URL", "") or "").strip().rstrip("/")
    if configured_base:
        return configured_base
    return request.build_absolute_uri("/").rstrip("/")


def _request_base_url(request: HttpRequest) -> str:
    return request.build_absolute_uri("/").rstrip("/")


def _build_absolute_media_url(request: HttpRequest, relative_url: str, *, prefer_public_base: bool = True) -> str:
    text = str(relative_url or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if not text.startswith("/"):
        text = f"/{text}"
    base_url = _public_base_url_from_request(request) if prefer_public_base else _request_base_url(request)
    return f"{base_url}{text}"


def _get_runtime_exotel_wait_audio() -> dict:
    cached = cache.get(RUNTIME_EXOTEL_WAIT_AUDIO_CACHE_KEY)
    if isinstance(cached, dict):
        wait_url = str(cached.get("wait_url") or "").strip()
        if wait_url:
            return {
                "wait_url": wait_url,
                "file_name": str(cached.get("file_name") or ""),
                "uploaded_at": str(cached.get("uploaded_at") or ""),
                "source": "uploaded",
            }

    env_wait_url = str(os.getenv("EXOTEL_WAIT_URL", "") or "").strip()
    if env_wait_url:
        return {"wait_url": env_wait_url, "file_name": "", "uploaded_at": "", "source": "env"}
    return {"wait_url": "", "file_name": "", "uploaded_at": "", "source": "none"}


def _assign_runtime_exotel_wait_url(provider: ExotelProvider) -> str:
    wait_audio = _get_runtime_exotel_wait_audio()
    wait_url = str(wait_audio.get("wait_url") or "").strip()
    if wait_url:
        provider.wait_url = wait_url
    return wait_url


def _active_call_not_ended_filter() -> Q:
    # Exotel can sometimes send epoch placeholder end-times for active calls.
    # Treat those rows as not-ended to avoid accidental parallel dispatch.
    cutoff = timezone.make_aware(datetime(2000, 1, 1), timezone.get_current_timezone())
    return Q(ended_at__isnull=True) | Q(ended_at__lt=cutoff)


def _format_duration(call: CallSession) -> str:
    display_status = _derive_display_status(call)
    if not _is_duration_eligible_status(display_status):
        return "-"

    duration_seconds = _duration_seconds_for_call(call)
    if duration_seconds is not None and duration_seconds >= 0:
        return _format_seconds(duration_seconds)

    return "-"


def _format_seconds(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _first_present(mapping: dict, keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def _parse_provider_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return None

    text = str(value).strip()
    if not text:
        return None

    candidates = [text]
    if text.endswith("Z"):
        candidates.append(f"{text[:-1]}+00:00")

    for candidate in candidates:
        dt = parse_datetime(candidate)
        if dt:
            if timezone.is_naive(dt):
                return timezone.make_aware(dt, timezone.get_current_timezone())
            return dt

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%d-%m-%Y %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if timezone.is_naive(dt):
                return timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except ValueError:
            continue

    return None


def _normalize_phone(value: str) -> str:
    if not value:
        return ""

    raw = value.strip().replace(" ", "")
    if raw.startswith("+"):
        candidate = "+" + "".join(ch for ch in raw[1:] if ch.isdigit())
    else:
        candidate = "".join(ch for ch in raw if ch.isdigit())

    if not candidate:
        return ""

    if candidate.startswith("91") and not candidate.startswith("+"):
        candidate = f"+{candidate}"

    if candidate.isdigit() and len(candidate) == 10:
        candidate = f"+91{candidate}"

    return candidate


def _parse_json_like_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        if "=" in raw and ("&" in raw or ";" in raw):
            pairs = parse_qsl(raw.replace(";", "&"), keep_blank_values=True)
            if pairs:
                return {str(k): v for k, v in pairs}
    return {}


def _parse_positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _parse_non_negative_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else default
    except (TypeError, ValueError):
        return default


def _load_json_body(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _load_webhook_payload(request: HttpRequest) -> dict:
    content_type = str(request.content_type or "").lower()
    if "json" in content_type:
        return _load_json_body(request)

    form_payload = request.POST.dict()
    if form_payload:
        return form_payload

    raw_body = request.body.decode("utf-8", errors="ignore")
    if not raw_body:
        return {}

    return dict(parse_qsl(raw_body, keep_blank_values=True))


def _resolve_max_call_duration_seconds(override_value: object = None) -> int | None:
    configured_default = _parse_non_negative_int(
        getattr(settings, "EXOTEL_MAX_CALL_DURATION_SECONDS", 0),
        0,
    )

    if override_value in (None, ""):
        return configured_default or None

    try:
        parsed = int(override_value)
    except (TypeError, ValueError):
        return configured_default or None

    if parsed <= 0:
        return None
    return parsed


def _normalize_amd(answered_by: str | None) -> str | None:
    if not answered_by:
        return None

    value = answered_by.strip().lower()
    if value in {"human", "person", "live"}:
        return "human"
    if value in {"machine", "voicemail", "answering_machine"}:
        return "machine"
    if value in {"notsure", "not_sure", "not sure", "unknown", "silence"}:
        return "unknown"
    return value


def _pick_value(row: dict, keys: list[str]) -> str:
    # Try exact key match first.
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    # Fallback to normalized header lookup so variants like
    # "Phone number", "Phone Number", "phone_number" all work.
    normalized_row: dict[str, str] = {}
    for row_key, row_value in row.items():
        if row_value is None or not str(row_value).strip():
            continue
        normalized_key = re.sub(r"[^a-z0-9]+", "", str(row_key).strip().lower())
        if normalized_key and normalized_key not in normalized_row:
            normalized_row[normalized_key] = str(row_value).strip()

    for key in keys:
        normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).strip().lower())
        value = normalized_row.get(normalized_key)
        if value:
            return value

    return ""


def _extract_campaign_settings(source: object) -> dict:
    if not source or not hasattr(source, "get"):
        return {}

    settings: dict[str, object] = {}

    for key in ("dialing_mode", "caller_id", "description"):
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            settings[key] = text

    for key in ("delay_between_calls", "max_retries"):
        value = source.get(key)
        parsed = _parse_positive_int(value, 0)
        if parsed > 0:
            settings[key] = parsed

    agent_value = source.get("agent_id")
    if agent_value is not None:
        agent_text = str(agent_value).strip()
        if agent_text:
            settings["agent_id"] = agent_text

    return settings
