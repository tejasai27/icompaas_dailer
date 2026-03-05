import csv
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import threading
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlparse
from uuid import UUID, uuid4

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import IntegrityError, connection, transaction
from django.db.models import Max, Q
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.telephony.base import DialRequest
from apps.telephony.exotel import ExotelProvider
from apps.telephony.factory import get_provider

from .models import (
    AgentProfile,
    AgentStatus,
    Campaign,
    CampaignDialingMode,
    CampaignLead,
    CampaignLeadStatus,
    CampaignStatus,
    CallDisposition,
    CRMSyncLog,
    CallSession,
    CallStatus,
    CallOutcome,
    HubSpotDealAssociationMode,
    HubSpotIntegrationSettings,
    Lead,
    LeadDialState,
    ProviderType,
    RecordingAsset,
    RecordingSource,
    TranscriptStatus,
)

logger = logging.getLogger("dialer.campaign")

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
HUBSPOT_API_BASE = "https://api.hubapi.com"
HUBSPOT_TIMEOUT_SECONDS = max(3.0, float(os.getenv("HUBSPOT_TIMEOUT_SECONDS", "12") or 12))
_WHISPER_MODEL_INSTANCE = None
_WHISPER_MODEL_LOCK = threading.Lock()
_CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE: bool | None = None


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


def _normalize_transcript_segments(raw_segments: object) -> list[dict]:
    if not isinstance(raw_segments, list):
        return []

    normalized: list[dict] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue

        start_raw = item.get("start", item.get("start_time", item.get("from")))
        end_raw = item.get("end", item.get("end_time", item.get("to")))

        try:
            start = max(0.0, float(start_raw)) if start_raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            start = 0.0

        end: float | None
        try:
            end = max(0.0, float(end_raw)) if end_raw not in (None, "") else None
        except (TypeError, ValueError):
            end = None

        if end is not None and end < start:
            end = start

        normalized.append(
            {
                "start": round(start, 3),
                "end": round(end, 3) if end is not None else None,
                "text": text,
            }
        )

    for index, segment in enumerate(normalized):
        if segment.get("end") is not None:
            continue
        next_start = None
        if index + 1 < len(normalized):
            next_start = normalized[index + 1].get("start")
        segment["end"] = round(float(next_start), 3) if next_start is not None else round(float(segment["start"]) + 1.2, 3)

    return normalized


_AUTO_TRANSCRIPTION_LANGUAGE_VALUES = {"", "auto", "any", "mixed", "multilingual", "default"}
_TRANSCRIPTION_LANGUAGE_ALIASES = {
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "telugu": "te",
    "te-in": "te",
}


def _normalize_transcription_language(value: object) -> tuple[str | None, bool]:
    raw_text = str(value or "").strip()
    if not raw_text:
        return None, True

    key = raw_text.lower().replace("_", "-")
    if key in _AUTO_TRANSCRIPTION_LANGUAGE_VALUES:
        return None, True

    key = _TRANSCRIPTION_LANGUAGE_ALIASES.get(key, key)
    if re.fullmatch(r"[a-z]{2}", key):
        return key, True

    return None, False


def _get_request_transcription_language(request: HttpRequest) -> tuple[str | None, str]:
    content_type = str(request.content_type or "").lower()
    payload = _load_json_body(request) if "json" in content_type else {}

    candidates = [
        payload.get("language"),
        request.POST.get("language"),
        request.GET.get("language"),
    ]
    for raw in candidates:
        if raw is None:
            continue
        language, ok = _normalize_transcription_language(raw)
        return language, "" if ok else str(raw).strip()

    return None, ""


def _resolved_transcription_language(language: str | None = None) -> str | None:
    if language is not None:
        parsed, ok = _normalize_transcription_language(language)
        if ok:
            return parsed
    parsed_default, default_ok = _normalize_transcription_language(WHISPER_LANGUAGE)
    if default_ok:
        return parsed_default
    return None


def _is_english_language_code(value: object) -> bool:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        return True
    if text in {"en", "english", "eng", "en-us", "en-gb", "en-in", "en-au"}:
        return True
    return text.startswith("en-")


def _recording_transcription_progress_cache_key(recording_id: int) -> str:
    return f"{TRANSCRIPTION_PROGRESS_CACHE_PREFIX}{recording_id}"


def _set_recording_transcription_progress(
    recording: RecordingAsset,
    percent: int | float,
    *,
    stage: str = "",
    status: str | None = None,
    detail: str = "",
) -> None:
    if not recording or not recording.id:
        return
    try:
        normalized_percent = int(round(float(percent)))
    except (TypeError, ValueError):
        return
    normalized_percent = max(0, min(100, normalized_percent))

    payload = {
        "percent": normalized_percent,
        "stage": str(stage or "").strip(),
        "status": str(status or recording.transcript_status or "").strip().lower(),
        "detail": str(detail or "").strip()[:400],
        "updated_at": timezone.now().isoformat(),
    }
    cache.set(
        _recording_transcription_progress_cache_key(int(recording.id)),
        payload,
        timeout=TRANSCRIPTION_PROGRESS_TTL_SECONDS,
    )


def _get_recording_transcription_progress(recording: RecordingAsset) -> dict:
    status = str(recording.transcript_status or "").strip().lower()
    default_percent = 5 if status == TranscriptStatus.PROCESSING else 0
    default_stage = "processing" if status == TranscriptStatus.PROCESSING else "idle"
    if status == TranscriptStatus.COMPLETED:
        default_percent = 100
        default_stage = "completed"
    elif status == TranscriptStatus.FAILED:
        default_percent = 0
        default_stage = "failed"

    payload = cache.get(_recording_transcription_progress_cache_key(int(recording.id)))
    percent = default_percent
    stage = default_stage
    updated_at = recording.updated_at.isoformat() if recording.updated_at else None

    if isinstance(payload, dict):
        try:
            percent = int(payload.get("percent"))
        except (TypeError, ValueError):
            percent = default_percent
        percent = max(0, min(100, percent))
        stage = str(payload.get("stage") or stage).strip() or default_stage
        payload_updated_at = str(payload.get("updated_at") or "").strip()
        if payload_updated_at:
            updated_at = payload_updated_at

    if status == TranscriptStatus.COMPLETED:
        percent = 100
        stage = "completed"
    elif status == TranscriptStatus.FAILED:
        stage = "failed"
        percent = min(percent, 99)

    return {
        "percent": percent,
        "stage": stage,
        "updated_at": updated_at,
    }


def _recording_audio_url(recording: RecordingAsset, request: HttpRequest | None = None) -> str:
    audio_url = str(recording.external_audio_url or "").strip()
    if not audio_url and recording.audio_file:
        try:
            audio_url = str(recording.audio_file.url or "").strip()
        except Exception:
            audio_url = ""

    if request and audio_url.startswith("/"):
        # Browser playback should use the same host that served the API response.
        return _build_absolute_media_url(request, audio_url, prefer_public_base=False)
    return audio_url


def _serialize_recording_asset(recording: RecordingAsset, request: HttpRequest | None = None, include_transcript: bool = False) -> dict:
    title = str(recording.title or "").strip()
    if not title and recording.call and recording.call.lead:
        started_at = recording.call.started_at or recording.call.created_at
        stamp = started_at.strftime("%Y-%m-%d %H:%M") if started_at else ""
        title = f"{recording.call.lead.full_name}{f' ({stamp})' if stamp else ''}"
    progress = _get_recording_transcription_progress(recording)

    result = {
        "id": recording.id,
        "public_id": str(recording.public_id),
        "source": recording.source,
        "title": title or "Untitled Recording",
        "audio_url": _recording_audio_url(recording, request=request),
        "duration_seconds": recording.duration_seconds,
        "duration_formatted": _format_seconds(recording.duration_seconds or 0) if recording.duration_seconds else "-",
        "transcript_status": recording.transcript_status,
        "transcript_error": str(recording.transcript_error or ""),
        "has_transcript": bool(str(recording.transcript_text or "").strip()),
        "created_at": recording.created_at.isoformat() if recording.created_at else None,
        "updated_at": recording.updated_at.isoformat() if recording.updated_at else None,
        "call_id": recording.call_id,
        "call_public_id": str(recording.call.public_id) if recording.call else "",
        "provider_call_uuid": str(recording.call.provider_call_uuid) if recording.call else "",
        "contact_name": recording.call.lead.full_name if recording.call and recording.call.lead else "",
        "contact_phone": recording.call.lead.phone_e164 if recording.call and recording.call.lead else "",
        "agent_name": recording.call.agent.display_name if recording.call and recording.call.agent else "",
        "transcript_progress_percent": progress["percent"],
        "transcript_progress_stage": progress["stage"],
        "transcript_progress_updated_at": progress["updated_at"],
    }
    if include_transcript:
        result["transcript_text"] = str(recording.transcript_text or "")
        result["transcript_segments"] = _normalize_transcript_segments(recording.transcript_segments)
    return result


def _extract_call_transcript_payload(call: CallSession) -> dict:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    status = str(raw_payload.get("transcript_status") or "").strip().lower()
    text = str(raw_payload.get("transcript") or "").strip()
    segments = _normalize_transcript_segments(raw_payload.get("transcript_segments"))
    if status not in {TranscriptStatus.NONE, TranscriptStatus.PROCESSING, TranscriptStatus.COMPLETED, TranscriptStatus.FAILED}:
        status = TranscriptStatus.COMPLETED if text else TranscriptStatus.NONE
    if text and status == TranscriptStatus.NONE:
        status = TranscriptStatus.COMPLETED
    return {
        "status": status or TranscriptStatus.NONE,
        "text": text,
        "segments": segments,
    }


def _upsert_recording_asset_from_call(call: CallSession) -> tuple[RecordingAsset | None, bool]:
    recording_url = str(call.recording_url or "").strip()
    if not recording_url:
        return None, False

    started_at = call.started_at or call.created_at
    title = call.lead.full_name if call.lead else "Call Recording"
    if started_at:
        title = f"{title} ({started_at.strftime('%Y-%m-%d %H:%M')})"

    transcript_payload = _extract_call_transcript_payload(call)
    defaults = {
        "source": RecordingSource.EXOTEL,
        "title": title[:255],
        "external_audio_url": recording_url,
        "duration_seconds": _duration_seconds_for_call(call) or None,
        "transcript_status": transcript_payload["status"] or TranscriptStatus.NONE,
        "transcript_text": transcript_payload["text"],
        "transcript_segments": transcript_payload["segments"],
    }

    recording, created = RecordingAsset.objects.get_or_create(
        call=call,
        defaults=defaults,
    )

    update_fields: list[str] = []
    if recording.source != RecordingSource.EXOTEL:
        recording.source = RecordingSource.EXOTEL
        update_fields.append("source")
    if recording.external_audio_url != recording_url:
        recording.external_audio_url = recording_url
        update_fields.append("external_audio_url")
    if title and recording.title != title[:255]:
        recording.title = title[:255]
        update_fields.append("title")

    duration_seconds = _duration_seconds_for_call(call) or None
    if duration_seconds and recording.duration_seconds != duration_seconds:
        recording.duration_seconds = duration_seconds
        update_fields.append("duration_seconds")

    if transcript_payload["text"]:
        if recording.transcript_text != transcript_payload["text"]:
            recording.transcript_text = transcript_payload["text"]
            update_fields.append("transcript_text")
        normalized_segments = transcript_payload["segments"]
        if normalized_segments and recording.transcript_segments != normalized_segments:
            recording.transcript_segments = normalized_segments
            update_fields.append("transcript_segments")
        if recording.transcript_status != TranscriptStatus.COMPLETED:
            recording.transcript_status = TranscriptStatus.COMPLETED
            update_fields.append("transcript_status")
        if recording.transcript_error:
            recording.transcript_error = ""
            update_fields.append("transcript_error")
    elif recording.transcript_status in {TranscriptStatus.NONE, TranscriptStatus.PROCESSING}:
        new_status = transcript_payload["status"] or TranscriptStatus.NONE
        if new_status != recording.transcript_status:
            recording.transcript_status = new_status
            update_fields.append("transcript_status")

    if update_fields:
        recording.save(update_fields=list(dict.fromkeys(update_fields + ["updated_at"])))
    return recording, bool(created or update_fields)


def _sync_recording_assets_from_exotel_calls(sync_exotel: bool, sync_limit: int) -> dict:
    sync_limit = max(1, min(int(sync_limit or 100), 500))

    if sync_exotel:
        calls_for_sync = list(
            CallSession.objects.select_related("lead", "agent")
            .filter(provider=ProviderType.EXOTEL)
            .exclude(provider_call_uuid="")
            .order_by("-created_at")[:sync_limit]
        )
        if calls_for_sync:
            _sync_exotel_call_details(calls_for_sync, max_fetch=sync_limit)

    calls_with_recordings = list(
        CallSession.objects.select_related("lead", "agent")
        .exclude(recording_url="")
        .order_by("-created_at")[: sync_limit * 3]
    )

    created = 0
    updated = 0
    processed = 0
    for call in calls_with_recordings:
        recording, changed = _upsert_recording_asset_from_call(call)
        if not recording:
            continue
        processed += 1
        _schedule_recording_auto_transcription(recording, reason="recordings_sync")
        if changed:
            if recording.created_at and recording.updated_at and recording.created_at == recording.updated_at:
                created += 1
            else:
                updated += 1

    return {
        "processed_calls": processed,
        "created": created,
        "updated": updated,
        "sync_exotel": bool(sync_exotel),
    }


def _looks_like_exotel_url(audio_url: str) -> bool:
    parsed = urlparse(str(audio_url or "").strip())
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return False
    if "exotel" in host:
        return True
    configured_host = str(os.getenv("EXOTEL_SUBDOMAIN", "") or "").replace("@", "").strip().lower()
    return bool(configured_host and configured_host in host)


def _exotel_recording_auth() -> tuple[str, str] | None:
    api_key = str(os.getenv("EXOTEL_API_KEY") or "").strip()
    api_token = str(os.getenv("EXOTEL_API_TOKEN") or "").strip()
    if not api_key or not api_token:
        return None
    return (api_key, api_token)


def _download_audio_to_tempfile(audio_url: str) -> tuple[str | None, str | None, str | None]:
    url_text = str(audio_url or "").strip()
    if not url_text:
        return None, None, "missing_audio_url"

    request_kwargs: dict = {
        "timeout": 120,
        "stream": True,
    }
    if _looks_like_exotel_url(url_text):
        auth = _exotel_recording_auth()
        if auth:
            request_kwargs["auth"] = auth

    try:
        response = requests.get(url_text, **request_kwargs)
    except requests.RequestException as exc:
        return None, None, str(exc)

    if response.status_code >= 400:
        return None, None, f"audio_download_failed_http_{response.status_code}"

    content_type = str(response.headers.get("content-type") or "").split(";")[0].strip().lower()
    parsed = urlparse(url_text)
    suffix = Path(parsed.path).suffix.strip()
    if not suffix:
        guessed_ext = mimetypes.guess_extension(content_type) if content_type else None
        suffix = guessed_ext or ".mp3"

    fd, temp_path = tempfile.mkstemp(prefix="recording_", suffix=suffix)
    os.close(fd)
    try:
        with open(temp_path, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                output.write(chunk)
    except Exception as exc:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return None, None, str(exc)

    return temp_path, content_type or None, None


def _is_retryable_audio_download_error(error_text: str) -> bool:
    value = str(error_text or "").strip().lower()
    if not value:
        return False
    retryable_tokens = (
        "audio_download_failed_http_403",
        "audio_download_failed_http_404",
        "audio_download_failed_http_408",
        "audio_download_failed_http_409",
        "audio_download_failed_http_423",
        "audio_download_failed_http_425",
        "audio_download_failed_http_429",
        "audio_download_failed_http_500",
        "audio_download_failed_http_502",
        "audio_download_failed_http_503",
        "audio_download_failed_http_504",
        "read timed out",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
    )
    return any(token in value for token in retryable_tokens)


def _coerce_duration_seconds_value(value: object) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return max(1, int(round(seconds)))


def _extract_audio_duration_seconds_from_file(file_path: str) -> int | None:
    path = str(file_path or "").strip()
    if not path:
        return None
    try:
        from mutagen import File as MutagenFile  # type: ignore
    except Exception:
        return None

    try:
        metadata = MutagenFile(path)
    except Exception:
        return None
    if metadata is None:
        return None
    info = getattr(metadata, "info", None)
    if info is None:
        return None
    return _coerce_duration_seconds_value(getattr(info, "length", None))


def _extract_duration_from_transcription_result(result: dict, transcript_segments: list[dict]) -> int | None:
    if not isinstance(result, dict):
        return None

    raw_payload = result.get("raw")
    if isinstance(raw_payload, dict):
        direct = _coerce_duration_seconds_value(raw_payload.get("duration"))
        if direct is not None:
            return direct
        meta = raw_payload.get("meta")
        if isinstance(meta, dict):
            meta_duration = _coerce_duration_seconds_value(meta.get("duration"))
            if meta_duration is not None:
                return meta_duration

    max_end = 0.0
    for item in transcript_segments:
        if not isinstance(item, dict):
            continue
        try:
            end_value = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if end_value > max_end:
            max_end = end_value
    return _coerce_duration_seconds_value(max_end)


def _get_whisper_model_instance():
    global _WHISPER_MODEL_INSTANCE
    if _WHISPER_MODEL_INSTANCE is not None:
        return _WHISPER_MODEL_INSTANCE

    with _WHISPER_MODEL_LOCK:
        if _WHISPER_MODEL_INSTANCE is not None:
            return _WHISPER_MODEL_INSTANCE
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError("faster-whisper is not installed. Add it to backend requirements.") from exc

        _WHISPER_MODEL_INSTANCE = WhisperModel(
            WHISPER_MODEL_NAME,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _WHISPER_MODEL_INSTANCE


def _transcribe_audio_with_local_whisper(
    file_path: str,
    language: str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict:
    try:
        language_hint = _resolved_transcription_language(language)
        model = _get_whisper_model_instance()
        segments_iter, info = model.transcribe(
            file_path,
            language=language_hint,
            beam_size=WHISPER_BEAM_SIZE,
            vad_filter=WHISPER_VAD_FILTER,
            condition_on_previous_text=WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            temperature=WHISPER_TEMPERATURE,
        )
    except Exception as exc:
        return {"ok": False, "error": f"local_whisper_error: {exc}"}

    segments: list[dict] = []
    texts: list[str] = []
    duration_hint = max(0.0, float(getattr(info, "duration", 0.0) or 0.0)) if info is not None else 0.0
    last_percent = 24
    if progress_callback:
        progress_callback(last_percent, "transcribing")
    for segment in segments_iter:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        start = max(0.0, float(getattr(segment, "start", 0.0) or 0.0))
        end = max(start, float(getattr(segment, "end", start) or start))
        if progress_callback and duration_hint > 0:
            ratio = max(0.0, min(1.0, end / duration_hint))
            percent = int(24 + (ratio * 70.0))
            if percent > last_percent:
                last_percent = percent
                progress_callback(last_percent, "transcribing")
        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }
        )
        texts.append(text)

    transcript_text = " ".join(texts).strip()
    if not transcript_text and segments:
        transcript_text = " ".join(str(segment.get("text") or "") for segment in segments).strip()

    meta = {}
    if info is not None:
        meta = {
            "language": str(getattr(info, "language", "") or ""),
            "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
            "duration": float(getattr(info, "duration", 0.0) or 0.0),
        }
    if progress_callback:
        progress_callback(96, "finalizing")

    detected_language = str(meta.get("language") or language_hint or "")
    return {
        "ok": True,
        "text": transcript_text,
        "segments": _normalize_transcript_segments(segments),
        "language": detected_language,
        "raw": {"provider": "local_whisper", "meta": meta},
    }


def _transcribe_audio_with_openai_whisper_api(
    file_path: str,
    mime_type: str | None = None,
    language: str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict:
    api_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY not configured"}

    model = str(os.getenv("OPENAI_WHISPER_MODEL") or "whisper-1").strip() or "whisper-1"
    language_hint = _resolved_transcription_language(language)
    openai_language_default = str(os.getenv("OPENAI_WHISPER_LANGUAGE") or "").strip()
    if not language_hint and openai_language_default:
        normalized, ok = _normalize_transcription_language(openai_language_default)
        if ok:
            language_hint = normalized
    timeout_seconds = max(30, int(os.getenv("OPENAI_WHISPER_TIMEOUT_SECONDS", "1800") or 1800))

    content_type = mime_type or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    headers = {"Authorization": f"Bearer {api_key}"}
    data: list[tuple[str, str]] = [
        ("model", model),
        ("response_format", "verbose_json"),
    ]
    if language_hint:
        data.append(("language", language_hint))
    if progress_callback:
        progress_callback(28, "uploading_audio")

    try:
        with open(file_path, "rb") as audio_file:
            files = {"file": (Path(file_path).name, audio_file, content_type)}
            response = requests.post(
                OPENAI_AUDIO_TRANSCRIPT_ENDPOINT,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout_seconds,
            )
    except (OSError, requests.RequestException) as exc:
        return {"ok": False, "error": str(exc)}
    if progress_callback:
        progress_callback(88, "finalizing")

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text}

    if response.status_code >= 400:
        error_text = ""
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                error_text = str(err.get("message") or err.get("type") or "")
            elif err:
                error_text = str(err)
        return {
            "ok": False,
            "error": error_text or f"openai_http_{response.status_code}",
            "raw": payload,
        }

    text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    segments = _normalize_transcript_segments(payload.get("segments") if isinstance(payload, dict) else [])
    if text and not segments:
        segments = [{"start": 0.0, "end": max(1.0, round(len(text) / 16.0, 3)), "text": text}]

    detected_language = (
        str(payload.get("language") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    return {
        "ok": True,
        "text": text,
        "segments": segments,
        "language": detected_language or language_hint or "",
        "raw": payload if isinstance(payload, dict) else {},
    }


def _transcribe_audio_with_whisper(
    file_path: str,
    mime_type: str | None = None,
    language: str | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict:
    backend = TRANSCRIPTION_BACKEND
    if backend in {"openai", "openai_whisper", "openai_api"}:
        openai_result = _transcribe_audio_with_openai_whisper_api(
            file_path,
            mime_type=mime_type,
            language=language,
            progress_callback=progress_callback,
        )
        if openai_result.get("ok"):
            return openai_result
        error_text = str(openai_result.get("error") or "").lower()
        if any(token in error_text for token in {"openai_http_413", "too large", "maximum content size", "content size limit"}):
            fallback_result = _transcribe_audio_with_local_whisper(
                file_path,
                language=language,
                progress_callback=progress_callback,
            )
            if fallback_result.get("ok"):
                raw_payload = fallback_result.get("raw") if isinstance(fallback_result.get("raw"), dict) else {}
                raw_payload["fallback_from"] = "openai_whisper"
                fallback_result["raw"] = raw_payload
                return fallback_result
        return openai_result
    return _transcribe_audio_with_local_whisper(
        file_path,
        language=language,
        progress_callback=progress_callback,
    )


def _save_call_transcript_payload(call: CallSession, transcript_status: str, text: str, segments: list[dict], error_text: str = "") -> None:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    raw_payload["transcript_status"] = transcript_status
    raw_payload["transcript"] = text
    raw_payload["transcript_segments"] = segments
    if error_text:
        raw_payload["transcript_error"] = error_text
    else:
        raw_payload.pop("transcript_error", None)
    call.raw_provider_payload = raw_payload
    call.save(update_fields=["raw_provider_payload"])


def _mark_recording_transcription_failed(recording: RecordingAsset, error_text: str) -> None:
    message = str(error_text or "transcription_failed").strip() or "transcription_failed"
    existing_payload = cache.get(_recording_transcription_progress_cache_key(int(recording.id))) if recording and recording.id else {}
    existing_percent = 0
    if isinstance(existing_payload, dict):
        try:
            existing_percent = int(existing_payload.get("percent"))
        except (TypeError, ValueError):
            existing_percent = 0
    recording.transcript_status = TranscriptStatus.FAILED
    recording.transcript_error = message[:1000]
    recording.save(update_fields=["transcript_status", "transcript_error", "updated_at"])
    _set_recording_transcription_progress(
        recording,
        max(0, min(99, existing_percent)),
        stage="failed",
        status=TranscriptStatus.FAILED,
        detail=recording.transcript_error,
    )
    if recording.call:
        _save_call_transcript_payload(recording.call, TranscriptStatus.FAILED, "", [], error_text=recording.transcript_error)


def _run_recording_transcription(recording: RecordingAsset, language: str | None = None) -> dict:
    temp_download_path = None
    audio_path = ""
    mime_type = None

    def _progress(percent: int, stage: str) -> None:
        _set_recording_transcription_progress(
            recording,
            percent,
            stage=stage,
            status=TranscriptStatus.PROCESSING,
        )

    try:
        _progress(10, "preparing_audio")
        if recording.audio_file:
            try:
                audio_path = str(recording.audio_file.path)
            except Exception:
                audio_path = ""
        if not audio_path:
            max_attempts = 1
            if recording.source == RecordingSource.EXOTEL:
                max_attempts = 1 + AUTO_TRANSCRIBE_DOWNLOAD_RETRIES

            download_error = ""
            for attempt in range(max_attempts):
                _progress(min(20, 10 + (attempt * 3)), "downloading_audio")
                audio_path, mime_type, download_error = _download_audio_to_tempfile(recording.external_audio_url)
                if audio_path and not download_error:
                    break
                if attempt + 1 >= max_attempts:
                    break
                if not _is_retryable_audio_download_error(download_error):
                    break
                time.sleep(AUTO_TRANSCRIBE_DOWNLOAD_RETRY_DELAY_SECONDS)

            if download_error or not audio_path:
                return {"ok": False, "error": download_error or "unable_to_download_audio"}
            temp_download_path = audio_path

        _progress(24, "transcribing")
        result = _transcribe_audio_with_whisper(
            audio_path,
            mime_type=mime_type,
            language=language,
            progress_callback=_progress,
        )
        if not result.get("ok"):
            return result

        detected_language = str(result.get("language") or "").strip().lower()
        if TRANSCRIPTION_ENGLISH_ONLY and detected_language and not _is_english_language_code(detected_language):
            return {"ok": False, "error": TRANSCRIPTION_NON_ENGLISH_ERROR}

        transcript_text = str(result.get("text") or "").strip()
        transcript_segments = _normalize_transcript_segments(result.get("segments"))
        duration_seconds = recording.duration_seconds or _extract_duration_from_transcription_result(result, transcript_segments)
        if not duration_seconds and audio_path:
            duration_seconds = _extract_audio_duration_seconds_from_file(audio_path)
        recording.transcript_text = transcript_text
        recording.transcript_segments = transcript_segments
        if duration_seconds:
            recording.duration_seconds = duration_seconds
        recording.transcript_status = TranscriptStatus.COMPLETED if transcript_text else TranscriptStatus.FAILED
        recording.transcript_error = "" if transcript_text else "empty_transcript"
        _progress(98, "saving")
        recording.save(
            update_fields=[
                "transcript_text",
                "transcript_segments",
                "duration_seconds",
                "transcript_status",
                "transcript_error",
                "updated_at",
            ]
        )

        if recording.call:
            _save_call_transcript_payload(
                recording.call,
                transcript_status=recording.transcript_status,
                text=recording.transcript_text,
                segments=recording.transcript_segments if isinstance(recording.transcript_segments, list) else [],
                error_text=recording.transcript_error,
            )

        _set_recording_transcription_progress(
            recording,
            100 if recording.transcript_status == TranscriptStatus.COMPLETED else 99,
            stage="completed" if recording.transcript_status == TranscriptStatus.COMPLETED else "failed",
            status=recording.transcript_status,
            detail=recording.transcript_error,
        )

        return {
            "ok": True,
            "recording": recording,
            "segments_count": len(transcript_segments),
        }
    finally:
        if temp_download_path:
            try:
                os.remove(temp_download_path)
            except OSError:
                pass


def _is_terminal_call_for_transcription(call: CallSession | None) -> bool:
    if not call:
        return False
    if call.ended_at:
        return True
    return call.status in {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.MACHINE_DETECTED}


def _is_recording_transcription_processing_stale(recording: RecordingAsset) -> bool:
    if recording.transcript_status != TranscriptStatus.PROCESSING:
        return False
    reference = recording.updated_at or recording.created_at
    if not reference:
        return True
    return (timezone.now() - reference).total_seconds() >= AUTO_TRANSCRIBE_STALE_PROCESSING_SECONDS


def _can_retry_failed_auto_transcription(recording: RecordingAsset, force: bool = False) -> bool:
    if force:
        return True
    if recording.transcript_status != TranscriptStatus.FAILED:
        return False
    reference = recording.updated_at or recording.created_at
    if not reference:
        return True
    return (timezone.now() - reference).total_seconds() >= AUTO_TRANSCRIBE_RETRY_FAILED_SECONDS


def _transcribe_recording_asset(recording: RecordingAsset, force: bool = False, language: str | None = None) -> dict:
    if recording.call and recording.source == RecordingSource.EXOTEL:
        _upsert_recording_asset_from_call(recording.call)
        recording.refresh_from_db()

    if not force:
        if recording.transcript_status == TranscriptStatus.PROCESSING and not _is_recording_transcription_processing_stale(recording):
            return {"ok": True, "recording": recording, "segments_count": 0, "skipped": "already_processing"}
        if recording.transcript_status == TranscriptStatus.COMPLETED and str(recording.transcript_text or "").strip():
            return {
                "ok": True,
                "recording": recording,
                "segments_count": len(recording.transcript_segments) if isinstance(recording.transcript_segments, list) else 0,
                "skipped": "already_completed",
            }
        if recording.transcript_status == TranscriptStatus.FAILED and not _can_retry_failed_auto_transcription(recording, force=force):
            return {"ok": True, "recording": recording, "segments_count": 0, "skipped": "recent_failed"}

    recording.transcript_status = TranscriptStatus.PROCESSING
    recording.transcript_error = ""
    recording.save(update_fields=["transcript_status", "transcript_error", "updated_at"])
    _set_recording_transcription_progress(
        recording,
        8,
        stage="queued",
        status=TranscriptStatus.PROCESSING,
    )
    if recording.call:
        _save_call_transcript_payload(recording.call, TranscriptStatus.PROCESSING, "", [], error_text="")

    try:
        transcribe_result = _run_recording_transcription(recording, language=language)
    except Exception as exc:
        _mark_recording_transcription_failed(recording, f"transcription_runtime_error: {exc}")
        return {"ok": False, "error": f"transcription_runtime_error: {exc}"}

    if not transcribe_result.get("ok"):
        error_text = str(transcribe_result.get("error") or "transcription_failed").strip()
        _mark_recording_transcription_failed(recording, error_text)
        return {"ok": False, "error": error_text}

    recording.refresh_from_db()
    return {
        "ok": True,
        "recording": recording,
        "segments_count": int(transcribe_result.get("segments_count") or 0),
    }


def _schedule_recording_auto_transcription(
    recording: RecordingAsset,
    reason: str = "",
    force: bool = False,
    language: str | None = None,
) -> bool:
    if not AUTO_TRANSCRIBE_RECORDINGS and not force:
        return False
    if not recording or not recording.id:
        return False
    if (
        recording.transcript_status == TranscriptStatus.PROCESSING
        and not force
        and not _is_recording_transcription_processing_stale(recording)
    ):
        return False
    if not force and recording.transcript_status == TranscriptStatus.COMPLETED:
        return False
    if not force and recording.transcript_status == TranscriptStatus.FAILED and not _can_retry_failed_auto_transcription(recording):
        return False
    if recording.call and recording.source == RecordingSource.EXOTEL and not _is_terminal_call_for_transcription(recording.call):
        return False

    lock_key = f"dialer:recording:auto_transcribe:{recording.id}"
    lock_token = f"{timezone.now().isoformat()}:{uuid4().hex}"
    if not cache.add(lock_key, lock_token, timeout=AUTO_TRANSCRIBE_LOCK_SECONDS):
        return False

    recording_id = int(recording.id)

    def _job() -> None:
        try:
            fresh = (
                RecordingAsset.objects.select_related("call__lead", "call__agent")
                .filter(id=recording_id)
                .first()
            )
            if not fresh:
                return
            if fresh.call and fresh.source == RecordingSource.EXOTEL and not _is_terminal_call_for_transcription(fresh.call):
                return
            _set_recording_transcription_progress(
                fresh,
                6,
                stage="queued",
                status=TranscriptStatus.PROCESSING,
            )
            _debug_runtime(
                "auto_transcribe_recording_start",
                {
                    "recording_id": fresh.id,
                    "public_id": str(fresh.public_id),
                    "status": str(fresh.transcript_status or ""),
                    "reason": reason,
                    "force": bool(force),
                    "language": str(language or ""),
                },
            )
            result = _transcribe_recording_asset(fresh, force=force, language=language)
            _debug_runtime(
                "auto_transcribe_recording_result",
                {
                    "recording_id": fresh.id,
                    "public_id": str(fresh.public_id),
                    "ok": bool(result.get("ok")),
                    "error": str(result.get("error") or ""),
                    "language": str(language or ""),
                    "reason": reason,
                    "force": bool(force),
                },
            )
        except Exception as exc:
            logger.exception("auto transcription failed for recording_id=%s", recording_id)
            fallback = RecordingAsset.objects.select_related("call").filter(id=recording_id).first()
            if fallback and fallback.transcript_status == TranscriptStatus.PROCESSING:
                _mark_recording_transcription_failed(fallback, f"auto_transcription_worker_error: {exc}")
        finally:
            current = cache.get(lock_key)
            if current == lock_token:
                cache.delete(lock_key)

    thread = threading.Thread(target=_job, daemon=True, name=f"auto-transcribe-{recording_id}")
    thread.start()
    return True


def _maybe_schedule_call_recording_transcription(call: CallSession, reason: str = "") -> bool:
    if not call or not str(call.recording_url or "").strip():
        return False
    recording, _ = _upsert_recording_asset_from_call(call)
    if not recording:
        return False
    return _schedule_recording_auto_transcription(recording, reason=reason)


def _active_call_not_ended_filter() -> Q:
    # Exotel can sometimes send epoch placeholder end-times for active calls.
    # Treat those rows as not-ended to avoid accidental parallel dispatch.
    cutoff = timezone.make_aware(datetime(2000, 1, 1), timezone.get_current_timezone())
    return Q(ended_at__isnull=True) | Q(ended_at__lt=cutoff)


def _serialize_agent(agent: AgentProfile) -> dict:
    user = getattr(agent, "user", None)
    username = ""
    email = ""
    if user:
        username_field = getattr(user, "USERNAME_FIELD", "username")
        username = str(getattr(user, username_field, "") or "")
        email = str(getattr(user, "email", "") or "")

    return {
        "id": agent.id,
        "display_name": agent.display_name,
        "status": agent.status,
        "user_id": agent.user_id,
        "username": username,
        "email": email,
    }


def _serialize_lead_row(lead: Lead) -> dict:
    dial_state = getattr(lead, "dial_state", None)
    status = dial_state.last_outcome if dial_state and dial_state.last_outcome else "pending"
    retry_count = dial_state.attempt_count if dial_state else 0
    last_called_at = dial_state.last_attempt_at.isoformat() if dial_state and dial_state.last_attempt_at else None
    metadata = lead.metadata if isinstance(lead.metadata, dict) else {}
    campaign_settings = metadata.get("campaign_settings")
    if not isinstance(campaign_settings, dict):
        campaign_settings = {}

    return {
        "id": lead.id,
        "name": lead.full_name,
        "full_name": lead.full_name,
        "phone": lead.phone_e164,
        "phone_e164": lead.phone_e164,
        "email": lead.email,
        "company": lead.company_name,
        "company_name": lead.company_name,
        "status": status,
        "retry_count": retry_count,
        "last_called_at": last_called_at,
        "owner_hint": lead.owner_hint,
        "timezone": lead.timezone,
        "external_id": lead.external_id,
        "campaign_name": str(metadata.get("campaign_name") or ""),
        "campaign_settings": campaign_settings,
    }


def _bulk_delete_lead_ids(lead_ids: list[int]) -> dict:
    if not lead_ids:
        return {
            "requested": 0,
            "deleted": 0,
            "deleted_ids": [],
            "deleted_rows": [],
            "blocked_in_progress": [],
            "blocked_with_history": [],
            "missing_ids": [],
        }

    leads = list(Lead.objects.filter(id__in=lead_ids).only("id", "full_name"))
    lead_name_by_id = {lead.id: lead.full_name for lead in leads}
    existing_ids = set(lead_name_by_id.keys())
    missing_ids = [lead_id for lead_id in lead_ids if lead_id not in existing_ids]

    active_statuses = [
        CallStatus.QUEUED,
        CallStatus.DIALING,
        CallStatus.RINGING,
        CallStatus.BRIDGED,
        CallStatus.HUMAN_DETECTED,
        CallStatus.MACHINE_DETECTED,
    ]
    active_call_ids = set(
        CallSession.objects.filter(lead_id__in=existing_ids)
        .filter(_active_call_not_ended_filter())
        .filter(status__in=active_statuses)
        .values_list("lead_id", flat=True)
    )
    call_history_ids = set(
        CallSession.objects.filter(lead_id__in=existing_ids).values_list("lead_id", flat=True)
    )

    blocked_in_progress = [lead_id for lead_id in lead_ids if lead_id in active_call_ids]
    blocked_with_history = [
        lead_id
        for lead_id in lead_ids
        if lead_id in existing_ids and lead_id not in active_call_ids and lead_id in call_history_ids
    ]
    deletable_ids = [
        lead_id
        for lead_id in lead_ids
        if lead_id in existing_ids and lead_id not in active_call_ids and lead_id not in call_history_ids
    ]

    if deletable_ids:
        Lead.objects.filter(id__in=deletable_ids).delete()

    return {
        "requested": len(lead_ids),
        "deleted": len(deletable_ids),
        "deleted_ids": deletable_ids,
        "deleted_rows": [{"id": lead_id, "name": str(lead_name_by_id.get(lead_id) or "")} for lead_id in deletable_ids],
        "blocked_in_progress": blocked_in_progress,
        "blocked_with_history": blocked_with_history,
        "missing_ids": missing_ids,
    }


def _username_base_from_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return cleaned[:40] if cleaned else "sdr"


def _build_unique_username(User: type, base: str, exclude_user_id: int | None = None) -> str:
    username_field = str(getattr(User, "USERNAME_FIELD", "username"))
    candidate = _username_base_from_text(base)
    suffix = 1
    while True:
        queryset = User.objects.filter(**{username_field: candidate})
        if exclude_user_id:
            queryset = queryset.exclude(id=exclude_user_id)
        if not queryset.exists():
            return candidate
        candidate = f"{_username_base_from_text(base)}_{suffix}"
        suffix += 1


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    db_ok = True
    cache_ok = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
    except Exception:
        db_ok = False

    try:
        cache.set("healthcheck", "ok", timeout=5)
        cache_ok = cache.get("healthcheck") == "ok"
    except Exception:
        cache_ok = False

    return JsonResponse(
        {"ok": db_ok and cache_ok, "service": "dialer-backend", "db": db_ok, "cache": cache_ok}
    )


@csrf_exempt
@require_GET
def get_exotel_wait_audio(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True, **_get_runtime_exotel_wait_audio()})


@csrf_exempt
@require_POST
def upload_exotel_wait_audio(request: HttpRequest) -> JsonResponse:
    upload = request.FILES.get("file") or request.FILES.get("audio")
    if not upload:
        return JsonResponse({"error": "audio file is required under 'file'"}, status=400)

    file_size = int(getattr(upload, "size", 0) or 0)
    if file_size > WAIT_AUDIO_MAX_BYTES:
        return JsonResponse(
            {
                "error": "file_too_large",
                "max_bytes": WAIT_AUDIO_MAX_BYTES,
                "message": "Audio file is too large",
            },
            status=400,
        )

    original_name = str(getattr(upload, "name", "") or "wait-audio").strip()
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if extension not in WAIT_AUDIO_ALLOWED_EXTENSIONS:
        return JsonResponse(
            {
                "error": "unsupported_file_type",
                "allowed_extensions": sorted(WAIT_AUDIO_ALLOWED_EXTENSIONS),
                "message": "Only mp3, wav, ogg, m4a are supported",
            },
            status=400,
        )

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name).strip("._")
    if not safe_name:
        safe_name = f"wait_audio.{extension}"

    storage_path = f"dialer/wait-audio/{timezone.now().strftime('%Y%m%d')}/{uuid4().hex}_{safe_name}"
    saved_path = default_storage.save(storage_path, upload)
    media_url = default_storage.url(saved_path)
    wait_url = _build_absolute_media_url(request, media_url)

    payload = {
        "wait_url": wait_url,
        "file_name": original_name,
        "uploaded_at": timezone.now().isoformat(),
    }
    cache.set(RUNTIME_EXOTEL_WAIT_AUDIO_CACHE_KEY, payload, timeout=None)

    return JsonResponse({"ok": True, **payload})


@csrf_exempt
@require_POST
def clear_exotel_wait_audio(request: HttpRequest) -> JsonResponse:
    cache.delete(RUNTIME_EXOTEL_WAIT_AUDIO_CACHE_KEY)
    return JsonResponse({"ok": True, "cleared": True, **_get_runtime_exotel_wait_audio()})


def _get_hubspot_settings(create: bool = False) -> HubSpotIntegrationSettings | None:
    def _is_missing_table_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "dialer_hubspotintegrationsettings" in message and (
            "does not exist" in message or "undefinedtable" in message or "no such table" in message
        )

    try:
        settings_row = HubSpotIntegrationSettings.objects.order_by("id").first()
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc):
            return None
        raise

    if settings_row or not create:
        return settings_row

    try:
        return HubSpotIntegrationSettings.objects.create()
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc):
            return None
        raise


def _mask_secret(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}{'*' * (len(text) - 8)}{text[-4:]}"


def _resolve_hubspot_access_token(settings_row: HubSpotIntegrationSettings | None = None, override_token: str = "") -> str:
    override_value = str(override_token or "").strip()
    if override_value:
        return override_value

    if settings_row:
        token = str(settings_row.access_token or "").strip()
        if token:
            return token

    return str(os.getenv("HUBSPOT_ACCESS_TOKEN", "") or "").strip()


def _serialize_hubspot_settings(settings_row: HubSpotIntegrationSettings | None) -> dict:
    mode_default = HubSpotDealAssociationMode.DEAL_ID
    if settings_row:
        mode_default = str(settings_row.deal_association_mode or HubSpotDealAssociationMode.DEAL_ID)

    if mode_default not in {HubSpotDealAssociationMode.DEAL_ID, HubSpotDealAssociationMode.DEAL_NAME}:
        mode_default = HubSpotDealAssociationMode.DEAL_ID

    active_token = _resolve_hubspot_access_token(settings_row)
    source = "none"
    if settings_row and str(settings_row.access_token or "").strip():
        source = "settings"
    elif str(os.getenv("HUBSPOT_ACCESS_TOKEN", "") or "").strip():
        source = "env"

    return {
        "enabled": bool(settings_row.enabled) if settings_row else False,
        "deal_association_mode": mode_default,
        "default_deal_id": str(settings_row.default_deal_id or "") if settings_row else "",
        "default_deal_name": str(settings_row.default_deal_name or "") if settings_row else "",
        "auto_sync_terminal_calls": bool(settings_row.auto_sync_terminal_calls) if settings_row else True,
        "auto_sync_on_disposition": bool(settings_row.auto_sync_on_disposition) if settings_row else True,
        "access_token_configured": bool(active_token),
        "access_token_masked": _mask_secret(active_token),
        "access_token_source": source,
        "updated_at": settings_row.updated_at.isoformat() if settings_row and settings_row.updated_at else None,
        "created_at": settings_row.created_at.isoformat() if settings_row and settings_row.created_at else None,
    }


def _hubspot_api_request(
    access_token: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    endpoint = f"{HUBSPOT_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    request_kwargs: dict[str, object] = {
        "method": method.upper(),
        "url": endpoint,
        "headers": headers,
        "timeout": HUBSPOT_TIMEOUT_SECONDS,
    }
    if payload is not None:
        request_kwargs["json"] = payload

    try:
        response = requests.request(**request_kwargs)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "endpoint": endpoint,
            "status_code": 0,
            "raw": {},
            "error": str(exc),
        }

    try:
        raw_payload = response.json()
    except ValueError:
        raw_payload = {"raw_text": response.text}

    if response.status_code < 400:
        return {
            "ok": True,
            "endpoint": endpoint,
            "status_code": response.status_code,
            "raw": raw_payload,
            "error": "",
        }

    error_text = ""
    if isinstance(raw_payload, dict):
        error_text = str(raw_payload.get("message") or raw_payload.get("error") or "").strip()
    if not error_text:
        error_text = f"hubspot_http_{response.status_code}"

    return {
        "ok": False,
        "endpoint": endpoint,
        "status_code": response.status_code,
        "raw": raw_payload,
        "error": error_text,
    }


def _first_non_empty_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _lookup_value(mapping: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _call_disposition_deal_fields_available(force_refresh: bool = False) -> bool:
    global _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE
    if not force_refresh and _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE is not None:
        return _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE

    try:
        with connection.cursor() as cursor:
            table_description = connection.introspection.get_table_description(cursor, CallDisposition._meta.db_table)
        columns = {str(getattr(column, "name", "") or "") for column in table_description}
        available = {"hubspot_deal_id", "hubspot_deal_name"}.issubset(columns)
    except (ProgrammingError, OperationalError):
        _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE = False
        return False

    _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE = available
    return _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE


def _call_session_select_related_fields(*, include_campaign: bool = False) -> tuple[str, ...]:
    fields = ["lead", "agent"]
    if include_campaign:
        fields.append("campaign")
    if _call_disposition_deal_fields_available():
        fields.append("disposition")
    return tuple(fields)


def _is_missing_disposition_deal_column_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "dialer_calldisposition" in message
        and ("hubspot_deal_id" in message or "hubspot_deal_name" in message)
        and ("does not exist" in message or "undefinedcolumn" in message)
    )


def _safe_get_call_disposition(call: CallSession) -> CallDisposition | None:
    global _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE
    if not _call_disposition_deal_fields_available():
        return None
    try:
        return getattr(call, "disposition", None)
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_disposition_deal_column_error(exc):
            _CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE = False
            return None
        raise


def _normalize_hubspot_deal_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d+(\.0+)?", text):
        try:
            return str(int(float(text)))
        except (TypeError, ValueError):
            return text
    return text


def _resolve_hubspot_deal_context(
    call: CallSession,
    settings_row: HubSpotIntegrationSettings | None,
    explicit_deal_id: str = "",
    explicit_deal_name: str = "",
) -> dict:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    init_request = raw_payload.get("init_request") if isinstance(raw_payload.get("init_request"), dict) else {}
    init_metadata = init_request.get("metadata") if isinstance(init_request.get("metadata"), dict) else {}
    lead_metadata = call.lead.metadata if isinstance(call.lead.metadata, dict) else {}
    disposition = _safe_get_call_disposition(call)

    deal_id_candidates = [
        explicit_deal_id,
        disposition.hubspot_deal_id if disposition else "",
        _lookup_value(init_request, ("deal_id", "dealId", "hubspot_deal_id", "hubspotDealId")),
        _lookup_value(init_metadata, ("deal_id", "dealId", "hubspot_deal_id", "hubspotDealId")),
        _lookup_value(lead_metadata, ("deal_id", "dealId", "hubspot_deal_id", "hubspotDealId")),
    ]
    deal_name_candidates = [
        explicit_deal_name,
        disposition.hubspot_deal_name if disposition else "",
        _lookup_value(init_request, ("deal_name", "dealName", "hubspot_deal_name", "hubspotDealName")),
        _lookup_value(init_metadata, ("deal_name", "dealName", "hubspot_deal_name", "hubspotDealName")),
        _lookup_value(lead_metadata, ("deal_name", "dealName", "hubspot_deal_name", "hubspotDealName")),
    ]

    mode = str(settings_row.deal_association_mode or HubSpotDealAssociationMode.DEAL_ID) if settings_row else HubSpotDealAssociationMode.DEAL_ID
    if mode not in {HubSpotDealAssociationMode.DEAL_ID, HubSpotDealAssociationMode.DEAL_NAME}:
        mode = HubSpotDealAssociationMode.DEAL_ID

    if mode == HubSpotDealAssociationMode.DEAL_NAME:
        deal_name = _first_non_empty_text(*deal_name_candidates)
        deal_id = _first_non_empty_text(*deal_id_candidates)
    else:
        deal_id = _first_non_empty_text(*deal_id_candidates)
        deal_name = _first_non_empty_text(*deal_name_candidates)

    return {
        "mode": mode,
        "deal_id": _normalize_hubspot_deal_id(deal_id),
        "deal_name": deal_name,
        "association_requested": bool(
            _first_non_empty_text(explicit_deal_id, explicit_deal_name)
            or _first_non_empty_text(deal_id, deal_name)
        ),
    }


def _find_hubspot_deal_id_by_name(access_token: str, deal_name: str) -> dict:
    lookup_name = str(deal_name or "").strip()
    if not lookup_name:
        return {"ok": True, "deal_id": "", "endpoint": "", "raw": {}, "status_code": 0}

    for operator in ("EQ", "CONTAINS_TOKEN"):
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "dealname",
                            "operator": operator,
                            "value": lookup_name,
                        }
                    ]
                }
            ],
            "properties": ["dealname"],
            "limit": 1,
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
        }
        result = _hubspot_api_request(access_token, "POST", "/crm/v3/objects/deals/search", payload=payload)
        if not result.get("ok"):
            return result

        raw_payload = result.get("raw")
        if not isinstance(raw_payload, dict):
            continue

        rows = raw_payload.get("results")
        if not isinstance(rows, list) or not rows:
            continue

        first_row = rows[0] if isinstance(rows[0], dict) else {}
        deal_id = _normalize_hubspot_deal_id(first_row.get("id"))
        if deal_id:
            result["deal_id"] = deal_id
            return result

    return {"ok": True, "deal_id": "", "endpoint": "", "raw": {}, "status_code": 200}


def _map_hubspot_call_status(display_status: str, outcome: str) -> str:
    normalized_status = str(display_status or "").strip().lower().replace("_", "-")
    normalized_outcome = str(outcome or "").strip().lower().replace("_", "-")

    if normalized_status == "sdr-cut":
        return "FAILED"
    if normalized_status in {"no-answer", "no answer"} or normalized_outcome == "no-answer":
        return "NO_ANSWER"
    if normalized_status == "busy" or normalized_outcome == "busy":
        return "BUSY"
    if normalized_status in {"failed", "cancelled", "canceled"}:
        return "FAILED"
    if normalized_status == "machine" or normalized_outcome in {"machine", "voicemail"}:
        return "VOICEMAIL"
    return "COMPLETED"


def _build_hubspot_call_body(
    call: CallSession,
    display_status: str,
    outcome: str,
    notes: str,
    deal_id: str,
    deal_name: str,
) -> str:
    lines = [
        f"Contact: {call.lead.full_name} ({call.lead.phone_e164})",
        f"Agent: {call.agent.display_name if call.agent else 'Unassigned'}",
        f"Campaign: {call.campaign.name if call.campaign else 'Direct Dial'}",
        f"Status: {display_status or call.status}",
        f"Outcome: {outcome or '-'}",
        f"Provider Call UUID: {call.provider_call_uuid or '-'}",
    ]
    if deal_id:
        lines.append(f"Deal ID: {deal_id}")
    if deal_name:
        lines.append(f"Deal Name: {deal_name}")
    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.append(notes)
    return "\n".join(lines)


def _build_hubspot_task_subject(call: CallSession) -> str:
    campaign_name = call.campaign.name if call.campaign else "Direct Dial"
    return f"Call follow-up: {call.lead.full_name} ({campaign_name})"


def _build_hubspot_sync_signature(
    call: CallSession,
    display_status: str,
    outcome: str,
    notes: str,
    deal_id: str,
    deal_name: str,
    duration_seconds: int | None,
) -> str:
    payload = {
        "call_public_id": str(call.public_id),
        "provider_call_uuid": str(call.provider_call_uuid or ""),
        "status": str(display_status or call.status),
        "outcome": str(outcome or ""),
        "notes": str(notes or ""),
        "deal_id": str(deal_id or ""),
        "deal_name": str(deal_name or ""),
        "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
        "recording_url": str(call.recording_url or ""),
        "ended_at": call.ended_at.isoformat() if call.ended_at else "",
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _record_hubspot_sync_log(
    call: CallSession,
    status: str,
    request_payload: dict,
    response_payload: dict,
    error_message: str = "",
) -> None:
    retry_count = CRMSyncLog.objects.filter(call=call, target="hubspot").count()
    CRMSyncLog.objects.create(
        call=call,
        target="hubspot",
        status=status,
        request_payload=request_payload,
        response_payload=response_payload,
        error_message=str(error_message or ""),
        retry_count=retry_count,
        last_attempt_at=timezone.now(),
    )


def _save_hubspot_sync_state(
    call: CallSession,
    *,
    call_object_id: str = "",
    task_object_id: str = "",
    deal_id: str = "",
    deal_name: str = "",
    sync_signature: str = "",
    sync_reason: str = "",
    status: str = "",
    error: str = "",
) -> None:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    state = raw_payload.get("hubspot_sync") if isinstance(raw_payload.get("hubspot_sync"), dict) else {}

    if call_object_id:
        state["call_object_id"] = call_object_id
    if task_object_id:
        state["task_object_id"] = task_object_id
    if deal_id:
        state["deal_id"] = deal_id
    if deal_name:
        state["deal_name"] = deal_name
    if sync_signature:
        state["last_sync_signature"] = sync_signature
    if sync_reason:
        state["last_sync_reason"] = sync_reason
    if status:
        state["last_status"] = status
    state["last_error"] = str(error or "")
    state["last_synced_at"] = timezone.now().isoformat()

    raw_payload["hubspot_sync"] = state
    call.raw_provider_payload = raw_payload
    call.save(update_fields=["raw_provider_payload"])


def _sync_call_to_hubspot(
    call: CallSession,
    *,
    reason: str = "",
    force: bool = False,
    explicit_deal_id: str = "",
    explicit_deal_name: str = "",
) -> dict:
    if not call or not call.id:
        return {"ok": False, "error": "call_not_found"}

    call = CallSession.objects.select_related(*_call_session_select_related_fields(include_campaign=True)).filter(id=call.id).first()
    if not call:
        return {"ok": False, "error": "call_not_found"}

    settings_row = _get_hubspot_settings(create=False)
    if settings_row:
        if reason == "terminal" and not settings_row.auto_sync_terminal_calls:
            return {"ok": True, "skipped": "terminal_sync_disabled"}
        if reason == "disposition" and not settings_row.auto_sync_on_disposition:
            return {"ok": True, "skipped": "disposition_sync_disabled"}
        if not settings_row.enabled:
            return {"ok": True, "skipped": "hubspot_disabled"}
    elif not _parse_bool(os.getenv("HUBSPOT_ENABLED"), False):
        return {"ok": True, "skipped": "hubspot_disabled"}

    access_token = _resolve_hubspot_access_token(settings_row=settings_row)
    if not access_token:
        return {"ok": False, "error": "hubspot_access_token_missing"}

    disposition = _safe_get_call_disposition(call)
    outcome = str(disposition.outcome or "") if disposition else ""
    notes = str(disposition.notes or "") if disposition else ""
    display_status = _derive_display_status(call)
    duration_seconds = _duration_seconds_for_call(call)

    deal_context = _resolve_hubspot_deal_context(
        call,
        settings_row=settings_row,
        explicit_deal_id=explicit_deal_id,
        explicit_deal_name=explicit_deal_name,
    )
    deal_id = _normalize_hubspot_deal_id(deal_context.get("deal_id"))
    deal_name = str(deal_context.get("deal_name") or "").strip()
    association_requested = bool(deal_context.get("association_requested"))

    deal_lookup_result: dict = {}
    if not deal_id and deal_name:
        deal_lookup_result = _find_hubspot_deal_id_by_name(access_token, deal_name)
        if not deal_lookup_result.get("ok"):
            request_payload = {
                "action": "resolve_deal",
                "reason": reason,
                "deal_name": deal_name,
                "call_public_id": str(call.public_id),
            }
            response_payload = {
                "deal_lookup": deal_lookup_result,
            }
            _record_hubspot_sync_log(
                call,
                CRMSyncLog.STATUS_FAILED,
                request_payload=request_payload,
                response_payload=response_payload,
                error_message=str(deal_lookup_result.get("error") or "hubspot_deal_lookup_failed"),
            )
            _save_hubspot_sync_state(
                call,
                deal_name=deal_name,
                sync_reason=reason,
                status=CRMSyncLog.STATUS_FAILED,
                error=str(deal_lookup_result.get("error") or "hubspot_deal_lookup_failed"),
            )
            return {"ok": False, "error": "hubspot_deal_lookup_failed", "details": deal_lookup_result}
        deal_id = _normalize_hubspot_deal_id(deal_lookup_result.get("deal_id"))

    if association_requested and not deal_id:
        error_text = "hubspot_deal_not_found"
        request_payload = {
            "action": "resolve_deal",
            "reason": reason,
            "deal_name": deal_name,
            "call_public_id": str(call.public_id),
        }
        response_payload = {"deal_lookup": deal_lookup_result}
        _record_hubspot_sync_log(
            call,
            CRMSyncLog.STATUS_FAILED,
            request_payload=request_payload,
            response_payload=response_payload,
            error_message=error_text,
        )
        _save_hubspot_sync_state(
            call,
            deal_name=deal_name,
            sync_reason=reason,
            status=CRMSyncLog.STATUS_FAILED,
            error=error_text,
        )
        return {"ok": False, "error": error_text}

    has_deal_context = bool(_first_non_empty_text(deal_id, deal_name))
    if not has_deal_context:
        _save_hubspot_sync_state(
            call,
            sync_reason=reason,
            status="skipped",
            error="",
        )
        return {"ok": True, "skipped": "hubspot_sync_skipped_without_deal_context"}

    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    hubspot_state = raw_payload.get("hubspot_sync") if isinstance(raw_payload.get("hubspot_sync"), dict) else {}
    existing_hubspot_call_id = str(hubspot_state.get("call_object_id") or "").strip()
    existing_hubspot_task_id = str(hubspot_state.get("task_object_id") or "").strip()

    sync_signature = _build_hubspot_sync_signature(
        call,
        display_status=display_status,
        outcome=outcome,
        notes=notes,
        deal_id=deal_id,
        deal_name=deal_name,
        duration_seconds=duration_seconds,
    )
    if not force and sync_signature and sync_signature == str(hubspot_state.get("last_sync_signature") or "").strip():
        return {
            "ok": True,
            "skipped": "unchanged",
            "hubspot_call_id": existing_hubspot_call_id,
            "hubspot_task_id": existing_hubspot_task_id,
            "deal_id": deal_id,
            "deal_name": deal_name,
        }

    init_request = raw_payload.get("init_request") if isinstance(raw_payload.get("init_request"), dict) else {}
    started_reference = call.started_at or call.created_at or timezone.now()
    timestamp_ms = int(started_reference.timestamp() * 1000)
    from_number = _first_non_empty_text(init_request.get("agent_phone"))
    to_number = _first_non_empty_text(init_request.get("lead_phone"), call.lead.phone_e164)

    properties: dict[str, object] = {
        "hs_timestamp": timestamp_ms,
        "hs_call_title": f"Dialer call - {call.lead.full_name}",
        "hs_call_body": _build_hubspot_call_body(
            call,
            display_status=display_status,
            outcome=outcome,
            notes=notes,
            deal_id=deal_id,
            deal_name=deal_name,
        ),
        "hs_call_status": _map_hubspot_call_status(display_status, outcome),
    }
    if from_number:
        properties["hs_call_from_number"] = from_number
    if to_number:
        properties["hs_call_to_number"] = to_number
    if duration_seconds is not None and duration_seconds >= 0:
        properties["hs_call_duration"] = int(duration_seconds * 1000)
    if call.recording_url:
        properties["hs_call_recording_url"] = str(call.recording_url)

    action = "update_call" if existing_hubspot_call_id else "create_call"
    call_payload = {"properties": properties}
    call_path = (
        f"/crm/v3/objects/calls/{existing_hubspot_call_id}"
        if existing_hubspot_call_id
        else "/crm/v3/objects/calls"
    )
    call_method = "PATCH" if existing_hubspot_call_id else "POST"

    call_result = _hubspot_api_request(access_token, call_method, call_path, payload=call_payload)
    if not call_result.get("ok"):
        request_payload = {
            "action": action,
            "reason": reason,
            "call_public_id": str(call.public_id),
            "hubspot_call_id": existing_hubspot_call_id,
            "properties": properties,
            "deal_id": deal_id,
            "deal_name": deal_name,
        }
        response_payload = {"call_result": call_result}
        _record_hubspot_sync_log(
            call,
            CRMSyncLog.STATUS_FAILED,
            request_payload=request_payload,
            response_payload=response_payload,
            error_message=str(call_result.get("error") or "hubspot_call_sync_failed"),
        )
        _save_hubspot_sync_state(
            call,
            call_object_id=existing_hubspot_call_id,
            task_object_id=existing_hubspot_task_id,
            deal_id=deal_id,
            deal_name=deal_name,
            sync_reason=reason,
            status=CRMSyncLog.STATUS_FAILED,
            error=str(call_result.get("error") or "hubspot_call_sync_failed"),
        )
        return {"ok": False, "error": "hubspot_call_sync_failed", "details": call_result}

    hubspot_call_id = existing_hubspot_call_id
    call_result_raw = call_result.get("raw")
    if not hubspot_call_id and isinstance(call_result_raw, dict):
        hubspot_call_id = str(call_result_raw.get("id") or "").strip()
    if not hubspot_call_id:
        request_payload = {
            "action": action,
            "reason": reason,
            "call_public_id": str(call.public_id),
            "properties": properties,
            "deal_id": deal_id,
            "deal_name": deal_name,
        }
        response_payload = {"call_result": call_result}
        error_text = "hubspot_call_id_missing"
        _record_hubspot_sync_log(
            call,
            CRMSyncLog.STATUS_FAILED,
            request_payload=request_payload,
            response_payload=response_payload,
            error_message=error_text,
        )
        _save_hubspot_sync_state(
            call,
            call_object_id=existing_hubspot_call_id,
            task_object_id=existing_hubspot_task_id,
            deal_id=deal_id,
            deal_name=deal_name,
            sync_reason=reason,
            status=CRMSyncLog.STATUS_FAILED,
            error=error_text,
        )
        return {"ok": False, "error": error_text}

    has_deal_context = bool(_first_non_empty_text(deal_id, deal_name))
    task_action = "skip_task_no_deal"
    task_properties: dict[str, object] = {}
    task_result: dict[str, object] = {"ok": True, "skipped": "task_not_created_without_deal_context"}
    hubspot_task_id = existing_hubspot_task_id
    if has_deal_context:
        task_status = "COMPLETED" if (call.ended_at or reason in {"terminal", "disposition", "manual"}) else "NOT_STARTED"
        task_properties = {
            "hs_timestamp": timestamp_ms,
            "hs_task_subject": _build_hubspot_task_subject(call),
            "hs_task_body": _build_hubspot_call_body(
                call,
                display_status=display_status,
                outcome=outcome,
                notes=notes,
                deal_id=deal_id,
                deal_name=deal_name,
            ),
            "hs_task_status": task_status,
            "hs_task_type": "CALL",
        }
        task_action = "update_task" if existing_hubspot_task_id else "create_task"
        task_payload = {"properties": task_properties}
        task_path = (
            f"/crm/v3/objects/tasks/{existing_hubspot_task_id}"
            if existing_hubspot_task_id
            else "/crm/v3/objects/tasks"
        )
        task_method = "PATCH" if existing_hubspot_task_id else "POST"
        task_result = _hubspot_api_request(access_token, task_method, task_path, payload=task_payload)
        if not task_result.get("ok"):
            request_payload = {
                "action": task_action,
                "reason": reason,
                "call_public_id": str(call.public_id),
                "hubspot_call_id": hubspot_call_id,
                "hubspot_task_id": existing_hubspot_task_id,
                "properties": task_properties,
                "deal_id": deal_id,
                "deal_name": deal_name,
            }
            response_payload = {"call_result": call_result, "task_result": task_result}
            error_text = str(task_result.get("error") or "hubspot_task_sync_failed")
            _record_hubspot_sync_log(
                call,
                CRMSyncLog.STATUS_FAILED,
                request_payload=request_payload,
                response_payload=response_payload,
                error_message=error_text,
            )
            _save_hubspot_sync_state(
                call,
                call_object_id=hubspot_call_id,
                task_object_id=existing_hubspot_task_id,
                deal_id=deal_id,
                deal_name=deal_name,
                sync_reason=reason,
                status=CRMSyncLog.STATUS_FAILED,
                error=error_text,
            )
            return {"ok": False, "error": "hubspot_task_sync_failed", "details": task_result}

        task_result_raw = task_result.get("raw")
        if not hubspot_task_id and isinstance(task_result_raw, dict):
            hubspot_task_id = str(task_result_raw.get("id") or "").strip()
        if not hubspot_task_id:
            request_payload = {
                "action": task_action,
                "reason": reason,
                "call_public_id": str(call.public_id),
                "hubspot_call_id": hubspot_call_id,
                "properties": task_properties,
                "deal_id": deal_id,
                "deal_name": deal_name,
            }
            response_payload = {"call_result": call_result, "task_result": task_result}
            error_text = "hubspot_task_id_missing"
            _record_hubspot_sync_log(
                call,
                CRMSyncLog.STATUS_FAILED,
                request_payload=request_payload,
                response_payload=response_payload,
                error_message=error_text,
            )
            _save_hubspot_sync_state(
                call,
                call_object_id=hubspot_call_id,
                deal_id=deal_id,
                deal_name=deal_name,
                sync_reason=reason,
                status=CRMSyncLog.STATUS_FAILED,
                error=error_text,
            )
            return {"ok": False, "error": error_text}

    call_association_result = {"ok": True, "skipped": "no_deal_association"}
    task_association_result = (
        {"ok": True, "skipped": "no_deal_association"}
        if has_deal_context
        else {"ok": True, "skipped": "task_not_created_without_deal_context"}
    )
    if deal_id:
        call_association_path = f"/crm/v4/objects/calls/{hubspot_call_id}/associations/default/deals/{deal_id}"
        call_association_result = _hubspot_api_request(access_token, "PUT", call_association_path, payload=None)
        if not call_association_result.get("ok"):
            request_payload = {
                "action": action,
                "reason": reason,
                "call_public_id": str(call.public_id),
                "hubspot_call_id": hubspot_call_id,
                "hubspot_task_id": hubspot_task_id,
                "properties": properties,
                "deal_id": deal_id,
                "deal_name": deal_name,
            }
            response_payload = {
                "call_result": call_result,
                "task_result": task_result,
                "call_association_result": call_association_result,
            }
            error_text = str(call_association_result.get("error") or "hubspot_call_deal_association_failed")
            _record_hubspot_sync_log(
                call,
                CRMSyncLog.STATUS_FAILED,
                request_payload=request_payload,
                response_payload=response_payload,
                error_message=error_text,
            )
            _save_hubspot_sync_state(
                call,
                call_object_id=hubspot_call_id,
                task_object_id=hubspot_task_id,
                deal_id=deal_id,
                deal_name=deal_name,
                sync_reason=reason,
                status=CRMSyncLog.STATUS_FAILED,
                error=error_text,
            )
            return {"ok": False, "error": "hubspot_call_deal_association_failed", "details": call_association_result}

        if has_deal_context and hubspot_task_id:
            task_association_path = f"/crm/v4/objects/tasks/{hubspot_task_id}/associations/default/deals/{deal_id}"
            task_association_result = _hubspot_api_request(access_token, "PUT", task_association_path, payload=None)
            if not task_association_result.get("ok"):
                request_payload = {
                    "action": task_action,
                    "reason": reason,
                    "call_public_id": str(call.public_id),
                    "hubspot_call_id": hubspot_call_id,
                    "hubspot_task_id": hubspot_task_id,
                    "properties": task_properties,
                    "deal_id": deal_id,
                    "deal_name": deal_name,
                }
                response_payload = {
                    "call_result": call_result,
                    "task_result": task_result,
                    "call_association_result": call_association_result,
                    "task_association_result": task_association_result,
                }
                error_text = str(task_association_result.get("error") or "hubspot_task_deal_association_failed")
                _record_hubspot_sync_log(
                    call,
                    CRMSyncLog.STATUS_FAILED,
                    request_payload=request_payload,
                    response_payload=response_payload,
                    error_message=error_text,
                )
                _save_hubspot_sync_state(
                    call,
                    call_object_id=hubspot_call_id,
                    task_object_id=hubspot_task_id,
                    deal_id=deal_id,
                    deal_name=deal_name,
                    sync_reason=reason,
                    status=CRMSyncLog.STATUS_FAILED,
                    error=error_text,
                )
                return {"ok": False, "error": "hubspot_task_deal_association_failed", "details": task_association_result}

    request_payload = {
        "action": action,
        "task_action": task_action,
        "reason": reason,
        "call_public_id": str(call.public_id),
        "hubspot_call_id": hubspot_call_id,
        "hubspot_task_id": hubspot_task_id,
        "call_properties": properties,
        "task_properties": task_properties,
        "deal_id": deal_id,
        "deal_name": deal_name,
    }
    response_payload = {
        "call_result": call_result,
        "task_result": task_result,
        "call_association_result": call_association_result,
        "task_association_result": task_association_result,
        "deal_lookup": deal_lookup_result,
    }
    _record_hubspot_sync_log(
        call,
        CRMSyncLog.STATUS_SUCCESS,
        request_payload=request_payload,
        response_payload=response_payload,
        error_message="",
    )
    _save_hubspot_sync_state(
        call,
        call_object_id=hubspot_call_id,
        task_object_id=hubspot_task_id,
        deal_id=deal_id,
        deal_name=deal_name,
        sync_signature=sync_signature,
        sync_reason=reason,
        status=CRMSyncLog.STATUS_SUCCESS,
        error="",
    )
    return {
        "ok": True,
        "action": action,
        "task_action": task_action,
        "hubspot_call_id": hubspot_call_id,
        "hubspot_task_id": hubspot_task_id,
        "deal_id": deal_id,
        "deal_name": deal_name,
        "call_association": call_association_result,
        "task_association": task_association_result,
    }


@csrf_exempt
def hubspot_settings(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        settings_row = _get_hubspot_settings(create=True)
        if not settings_row:
            return JsonResponse(
                {
                    "ok": False,
                    "warning": "hubspot settings schema is out of date. run: python manage.py migrate",
                    "settings": _serialize_hubspot_settings(None),
                }
            )
        return JsonResponse({"ok": True, "settings": _serialize_hubspot_settings(settings_row)})

    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    payload = _load_json_body(request)
    settings_row = _get_hubspot_settings(create=True)
    if not settings_row:
        return JsonResponse(
            {"error": "hubspot settings schema is out of date. run: python manage.py migrate"},
            status=500,
        )

    update_fields: list[str] = []

    if "enabled" in payload:
        settings_row.enabled = _parse_bool(payload.get("enabled"), settings_row.enabled)
        update_fields.append("enabled")

    if "deal_association_mode" in payload:
        mode = str(payload.get("deal_association_mode") or "").strip().lower()
        valid_modes = {HubSpotDealAssociationMode.DEAL_ID, HubSpotDealAssociationMode.DEAL_NAME}
        if mode not in valid_modes:
            return JsonResponse(
                {"error": "invalid_deal_association_mode", "allowed": sorted(valid_modes)},
                status=400,
            )
        settings_row.deal_association_mode = mode
        update_fields.append("deal_association_mode")

    if "default_deal_id" in payload:
        settings_row.default_deal_id = _normalize_hubspot_deal_id(payload.get("default_deal_id"))
        update_fields.append("default_deal_id")

    if "default_deal_name" in payload:
        settings_row.default_deal_name = str(payload.get("default_deal_name") or "").strip()[:255]
        update_fields.append("default_deal_name")

    if "auto_sync_terminal_calls" in payload:
        settings_row.auto_sync_terminal_calls = _parse_bool(
            payload.get("auto_sync_terminal_calls"),
            settings_row.auto_sync_terminal_calls,
        )
        update_fields.append("auto_sync_terminal_calls")

    if "auto_sync_on_disposition" in payload:
        settings_row.auto_sync_on_disposition = _parse_bool(
            payload.get("auto_sync_on_disposition"),
            settings_row.auto_sync_on_disposition,
        )
        update_fields.append("auto_sync_on_disposition")

    if _parse_bool(payload.get("clear_access_token"), False):
        settings_row.access_token = ""
        update_fields.append("access_token")
    elif "access_token" in payload:
        token_value = str(payload.get("access_token") or "").strip()
        if token_value:
            settings_row.access_token = token_value
            update_fields.append("access_token")

    if update_fields:
        settings_row.save(update_fields=list(dict.fromkeys(update_fields + ["updated_at"])))

    return JsonResponse({"ok": True, "settings": _serialize_hubspot_settings(settings_row)})


@csrf_exempt
@require_POST
def test_hubspot_settings(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    settings_row = _get_hubspot_settings(create=False)
    access_token = _resolve_hubspot_access_token(settings_row, override_token=str(payload.get("access_token") or ""))
    if not access_token:
        return JsonResponse({"ok": False, "error": "hubspot_access_token_missing"}, status=400)

    result = _hubspot_api_request(
        access_token,
        "GET",
        "/crm/v3/objects/deals?limit=1&properties=dealname",
        payload=None,
    )
    if not result.get("ok"):
        return JsonResponse(
            {
                "ok": False,
                "error": "hubspot_connection_failed",
                "details": result,
            },
            status=502,
        )

    sample_deal = None
    raw_payload = result.get("raw")
    if isinstance(raw_payload, dict):
        rows = raw_payload.get("results")
        if isinstance(rows, list) and rows:
            first = rows[0] if isinstance(rows[0], dict) else {}
            sample_deal = {
                "id": str(first.get("id") or ""),
                "name": str((first.get("properties") or {}).get("dealname") or "") if isinstance(first.get("properties"), dict) else "",
            }

    return JsonResponse({"ok": True, "message": "HubSpot connection successful", "sample_deal": sample_deal})


@csrf_exempt
@require_POST
def sync_call_to_hubspot(request: HttpRequest, call_public_id: UUID) -> JsonResponse:
    call = get_object_or_404(
        CallSession.objects.select_related(*_call_session_select_related_fields(include_campaign=True)),
        public_id=call_public_id,
    )
    payload = _load_json_body(request)
    result = _sync_call_to_hubspot(
        call,
        reason="manual",
        force=_parse_bool(payload.get("force"), True),
        explicit_deal_id=str(payload.get("deal_id") or "").strip(),
        explicit_deal_name=str(payload.get("deal_name") or "").strip(),
    )
    call.refresh_from_db()
    call = CallSession.objects.select_related(*_call_session_select_related_fields(include_campaign=True)).get(id=call.id)

    if result.get("ok") or result.get("skipped"):
        return JsonResponse({"ok": True, "result": result, "call": _serialize_call_log(call, include_raw=False)})
    return JsonResponse({"ok": False, "result": result, "call": _serialize_call_log(call, include_raw=False)}, status=502)


def _serialize_hubspot_record(log: CRMSyncLog, include_payload: bool = False) -> dict:
    request_payload = log.request_payload if isinstance(log.request_payload, dict) else {}
    response_payload = log.response_payload if isinstance(log.response_payload, dict) else {}

    call_result = response_payload.get("call_result") if isinstance(response_payload.get("call_result"), dict) else {}
    task_result = response_payload.get("task_result") if isinstance(response_payload.get("task_result"), dict) else {}
    call_result_raw = call_result.get("raw") if isinstance(call_result.get("raw"), dict) else {}
    task_result_raw = task_result.get("raw") if isinstance(task_result.get("raw"), dict) else {}

    call = log.call
    row = {
        "id": log.id,
        "target": log.target,
        "status": log.status,
        "retry_count": int(log.retry_count or 0),
        "error_message": str(log.error_message or ""),
        "action": str(request_payload.get("action") or ""),
        "task_action": str(request_payload.get("task_action") or ""),
        "reason": str(request_payload.get("reason") or ""),
        "deal_id": str(request_payload.get("deal_id") or ""),
        "deal_name": str(request_payload.get("deal_name") or ""),
        "hubspot_call_id": _first_non_empty_text(request_payload.get("hubspot_call_id"), call_result_raw.get("id")),
        "hubspot_task_id": _first_non_empty_text(request_payload.get("hubspot_task_id"), task_result_raw.get("id")),
        "call_id": call.id if call else None,
        "call_public_id": str(call.public_id) if call else "",
        "provider_call_uuid": str(call.provider_call_uuid or "") if call else "",
        "contact_name": call.lead.full_name if call and call.lead else "",
        "contact_phone": call.lead.phone_e164 if call and call.lead else "",
        "campaign_name": call.campaign.name if call and call.campaign else "Direct Dial",
        "agent_name": call.agent.display_name if call and call.agent else "Unassigned",
        "call_status": _derive_display_status(call) if call else "",
        "last_attempt_at": log.last_attempt_at.isoformat() if log.last_attempt_at else None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
    if include_payload:
        row["request_payload"] = request_payload
        row["response_payload"] = response_payload
    return row


@require_GET
def list_hubspot_records(request: HttpRequest) -> JsonResponse:
    page = _parse_positive_int(request.GET.get("page"), 1)
    page_size = min(_parse_positive_int(request.GET.get("page_size"), 20), 100)
    search = str(request.GET.get("search") or "").strip()
    status_filter = str(request.GET.get("status") or "").strip().lower()
    include_payload = _parse_bool(request.GET.get("include_payload"), False)

    valid_statuses = {CRMSyncLog.STATUS_PENDING, CRMSyncLog.STATUS_SUCCESS, CRMSyncLog.STATUS_FAILED}
    try:
        queryset = (
            CRMSyncLog.objects.select_related("call__lead", "call__agent", "call__campaign")
            .filter(target="hubspot")
            .order_by("-created_at", "-id")
        )
        if status_filter in valid_statuses:
            queryset = queryset.filter(status=status_filter)
        if search:
            queryset = queryset.filter(
                Q(call__lead__full_name__icontains=search)
                | Q(call__lead__phone_e164__icontains=search)
                | Q(call__campaign__name__icontains=search)
                | Q(call__provider_call_uuid__icontains=search)
                | Q(error_message__icontains=search)
            )

        count = queryset.count()
        offset = (page - 1) * page_size
        rows = list(queryset[offset : offset + page_size])
        results = [_serialize_hubspot_record(row, include_payload=include_payload) for row in rows]
        return JsonResponse({"count": count, "page": page, "page_size": page_size, "results": results})
    except (ProgrammingError, OperationalError) as exc:
        message = str(exc).lower()
        if "dialer_crmsynclog" in message or "dialer_hubspotintegrationsettings" in message:
            return JsonResponse({"error": "hubspot sync schema is out of date. run: python manage.py migrate"}, status=500)
        raise


@require_GET
def list_agents(request: HttpRequest) -> JsonResponse:
    agents = AgentProfile.objects.select_related("user").order_by("id")
    return JsonResponse(
        {
            "agents": [_serialize_agent(agent) for agent in agents]
        }
    )


@csrf_exempt
@require_POST
def create_agent(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    display_name = str(payload.get("display_name") or payload.get("name") or "").strip()
    if not display_name:
        return JsonResponse({"error": "display_name is required"}, status=400)

    status = str(payload.get("status") or AgentStatus.OFFLINE).strip().lower()
    valid_statuses = {choice[0] for choice in AgentProfile._meta.get_field("status").choices}
    if status not in valid_statuses:
        return JsonResponse({"error": "invalid status"}, status=400)

    email = str(payload.get("email") or "").strip()
    username_input = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "").strip()

    User = get_user_model()
    base_username = username_input or _username_base_from_text(email.split("@")[0] if "@" in email else display_name)
    username = _build_unique_username(User, base_username)

    user_kwargs: dict[str, object] = {User.USERNAME_FIELD: username}
    if hasattr(User, "email"):
        user_kwargs["email"] = email
    if hasattr(User, "first_name"):
        user_kwargs["first_name"] = display_name

    try:
        if password:
            user = User.objects.create_user(password=password, **user_kwargs)
        else:
            user = User.objects.create_user(password=None, **user_kwargs)
            user.set_unusable_password()
            user.save(update_fields=["password"])
    except IntegrityError:
        return JsonResponse({"error": "user_creation_failed"}, status=400)

    agent = AgentProfile.objects.create(
        user=user,
        display_name=display_name,
        status=status,
    )
    return JsonResponse({"ok": True, "agent": _serialize_agent(agent)}, status=201)


@csrf_exempt
@require_POST
def update_agent_status(request: HttpRequest, agent_id: int) -> JsonResponse:
    payload = _load_json_body(request)
    status = payload.get("status")

    if status not in {choice[0] for choice in AgentProfile._meta.get_field("status").choices}:
        return JsonResponse({"error": "invalid status"}, status=400)

    agent = get_object_or_404(AgentProfile, id=agent_id)
    agent.status = status
    agent.save(update_fields=["status", "last_state_change"])
    return JsonResponse({"agent_id": agent.id, "status": agent.status})


@csrf_exempt
@require_POST
def update_agent(request: HttpRequest, agent_id: int) -> JsonResponse:
    payload = _load_json_body(request)
    agent = get_object_or_404(AgentProfile.objects.select_related("user"), id=agent_id)
    user = agent.user

    display_name = str(payload.get("display_name") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    email = str(payload.get("email") or "").strip()
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "").strip()

    if status:
        valid_statuses = {choice[0] for choice in AgentProfile._meta.get_field("status").choices}
        if status not in valid_statuses:
            return JsonResponse({"error": "invalid status"}, status=400)

    User = get_user_model()

    with transaction.atomic():
        agent = AgentProfile.objects.select_related("user").select_for_update().get(id=agent.id)
        user = agent.user

        agent_update_fields: list[str] = []
        if display_name and display_name != agent.display_name:
            agent.display_name = display_name
            agent_update_fields.append("display_name")

        if status and status != agent.status:
            agent.status = status
            agent_update_fields.extend(["status", "last_state_change"])

        if agent_update_fields:
            agent.save(update_fields=list(dict.fromkeys(agent_update_fields)))

        user_update_fields: list[str] = []
        if hasattr(user, "email") and email and email != getattr(user, "email", ""):
            user.email = email
            user_update_fields.append("email")

        if username:
            current_username = str(getattr(user, User.USERNAME_FIELD, "") or "")
            if username != current_username:
                safe_username = _build_unique_username(User, username, exclude_user_id=user.id)
                setattr(user, User.USERNAME_FIELD, safe_username)
                user_update_fields.append(User.USERNAME_FIELD)

        if password:
            user.set_password(password)
            user_update_fields.append("password")

        if user_update_fields:
            user.save(update_fields=list(dict.fromkeys(user_update_fields)))

    agent.refresh_from_db()
    return JsonResponse({"ok": True, "agent": _serialize_agent(agent)})


@csrf_exempt
@require_POST
def delete_agent(request: HttpRequest, agent_id: int) -> JsonResponse:
    agent = get_object_or_404(AgentProfile, id=agent_id)
    active_call_exists = CallSession.objects.filter(
        agent_id=agent.id,
    ).filter(
        _active_call_not_ended_filter(),
    ).filter(
        status__in=[
            CallStatus.QUEUED,
            CallStatus.DIALING,
            CallStatus.RINGING,
            CallStatus.BRIDGED,
            CallStatus.HUMAN_DETECTED,
            CallStatus.MACHINE_DETECTED,
        ],
    ).exists()
    if active_call_exists:
        return JsonResponse(
            {"error": "agent_call_in_progress", "message": "This SDR has an active call"},
            status=409,
        )

    agent_name = agent.display_name
    user_id = agent.user_id
    agent.delete()
    return JsonResponse({"ok": True, "deleted": True, "agent_id": agent_id, "display_name": agent_name, "user_id": user_id})


@csrf_exempt
def list_campaigns(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        return create_campaign(request)
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    status_filter = str(request.GET.get("status") or "").strip().lower()

    try:
        queryset = Campaign.objects.select_related("assigned_agent").order_by("-created_at")
        if status_filter and status_filter in {choice[0] for choice in CampaignStatus.choices}:
            queryset = queryset.filter(status=status_filter)

        campaigns = list(queryset)
        results = [_serialize_campaign(campaign) for campaign in campaigns]
        return JsonResponse({"count": len(results), "results": results})
    except (ProgrammingError, OperationalError) as exc:
        message = str(exc).lower()
        if "dialer_campaign" in message or "campaign" in message:
            return JsonResponse(
                {"error": "campaign tables missing. run: python manage.py migrate"},
                status=500,
            )
        raise


@csrf_exempt
@require_POST
def create_campaign(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "campaign name is required"}, status=400)

    status = str(payload.get("status") or CampaignStatus.DRAFT).strip().lower()
    if status not in {choice[0] for choice in CampaignStatus.choices}:
        status = CampaignStatus.DRAFT

    dialing_mode = str(payload.get("dialing_mode") or CampaignDialingMode.POWER).strip().lower()
    if dialing_mode not in {choice[0] for choice in CampaignDialingMode.choices}:
        dialing_mode = CampaignDialingMode.POWER

    assigned_agent = None
    assigned_agent_id = payload.get("assigned_agent") or payload.get("assigned_agent_id") or payload.get("agent_id")
    if assigned_agent_id not in (None, ""):
        assigned_agent = get_object_or_404(AgentProfile, id=assigned_agent_id)

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    campaign = Campaign.objects.create(
        name=name,
        description=str(payload.get("description") or "").strip(),
        status=status,
        dialing_mode=dialing_mode,
        assigned_agent=assigned_agent,
        agent_phone=_normalize_phone(payload.get("agent_phone") or ""),
        caller_id=str(payload.get("caller_id") or "").strip(),
        delay_between_calls=_parse_positive_int(payload.get("delay_between_calls"), 15),
        max_retries=_parse_non_negative_int(payload.get("max_retries"), 0),
        metadata=metadata,
    )
    _log_campaign_event(
        campaign,
        "campaign_created",
        "Campaign created",
        details={
            "status": campaign.status,
            "dialing_mode": campaign.dialing_mode,
            "assigned_agent_id": campaign.assigned_agent_id,
        },
    )

    lead_ids_payload = payload.get("lead_ids")
    attached_count = 0
    if isinstance(lead_ids_payload, list) and lead_ids_payload:
        leads = list(Lead.objects.filter(id__in=[_parse_positive_int(lead_id, 0) for lead_id in lead_ids_payload]).order_by("id"))
        attached_count, _ = _attach_leads_to_campaign(campaign, leads)
        if attached_count:
            _log_campaign_event(
                campaign,
                "contacts_attached",
                "Contacts attached to campaign",
                details={"attached_count": attached_count},
            )

    response = _serialize_campaign(campaign)
    response["attached_leads"] = attached_count
    return JsonResponse(response, status=201)


@require_GET
def get_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign.objects.select_related("assigned_agent"), id=campaign_id)
    return JsonResponse(_serialize_campaign(campaign))


@csrf_exempt
@require_POST
def delete_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)
    active_call_exists = CallSession.objects.filter(
        campaign_id=campaign.id,
    ).filter(
        _active_call_not_ended_filter(),
    ).filter(
        status__in=[
            CallStatus.QUEUED,
            CallStatus.DIALING,
            CallStatus.RINGING,
            CallStatus.BRIDGED,
            CallStatus.HUMAN_DETECTED,
            CallStatus.MACHINE_DETECTED,
        ],
    ).exists()
    if active_call_exists:
        return JsonResponse(
            {"error": "campaign_call_in_progress", "message": "Active call in progress for this campaign"},
            status=409,
        )

    campaign_name = campaign.name
    campaign.delete()
    logger.info("campaign_deleted campaign_id=%s campaign_name=%s", campaign_id, campaign_name)
    return JsonResponse({"ok": True, "deleted": True, "campaign_id": campaign_id, "campaign_name": campaign_name})


@require_GET
def campaign_analytics(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)
    calls = list(CallSession.objects.select_related("lead", "agent").filter(campaign=campaign).order_by("-created_at"))
    rows = [_serialize_call_log(call) for call in calls]
    summary = _build_call_logs_summary(rows)

    durations = [_duration_seconds_for_call(call) for call in calls]
    durations = [value for value in durations if value is not None and value >= 0]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0
    connect_rate = round((summary["answered_calls"] / max(1, summary["total_calls"])) * 100, 1)

    return JsonResponse(
        {
            "campaign_id": campaign.id,
            "total_calls": summary["total_calls"],
            "answered_calls": summary["answered_calls"],
            "failed_calls": summary["failed_calls"],
            "no_answer_calls": summary["no_answer_calls"],
            "busy_calls": summary["busy_calls"],
            "connect_rate": connect_rate,
            "avg_duration_seconds": avg_duration,
            "status_counts": summary["status_counts"],
        }
    )


@require_GET
def campaign_queue(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)
    rows = list(
        CampaignLead.objects.select_related("lead")
        .filter(campaign=campaign)
        .order_by("queue_order", "id")
    )

    return JsonResponse(
        {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "count": len(rows),
            "results": [
                {
                    "id": row.id,
                    "lead_id": row.lead_id,
                    "contact_name": row.lead.full_name,
                    "contact_phone": row.lead.phone_e164,
                    "status": row.status,
                    "attempt_count": row.attempt_count,
                    "last_outcome": row.last_outcome,
                    "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
                    "queue_order": row.queue_order,
                }
                for row in rows
            ],
        }
    )


@csrf_exempt
@require_POST
def start_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign.objects.select_related("assigned_agent"), id=campaign_id)
    if campaign.status == CampaignStatus.ACTIVE:
        return JsonResponse({"error": "campaign already active"}, status=400)

    now = timezone.now()
    campaign.status = CampaignStatus.ACTIVE
    campaign.started_at = campaign.started_at or now
    campaign.paused_at = None
    campaign.completed_at = None
    campaign.save(update_fields=["status", "started_at", "paused_at", "completed_at", "updated_at"])
    _set_campaign_cooldown_until(campaign, None)
    _log_campaign_event(campaign, "campaign_started", "Campaign started")

    dispatch = _dispatch_campaign_next_call(campaign)
    _log_campaign_event(campaign, "dispatch_result", "Dispatch attempted after start", details=dispatch)
    campaign.refresh_from_db()
    return JsonResponse({"campaign": _serialize_campaign(campaign), "dispatch": dispatch})


@csrf_exempt
@require_POST
def pause_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)
    if campaign.status != CampaignStatus.ACTIVE:
        return JsonResponse({"error": "campaign is not active"}, status=400)

    campaign.status = CampaignStatus.PAUSED
    campaign.paused_at = timezone.now()
    campaign.save(update_fields=["status", "paused_at", "updated_at"])
    _log_campaign_event(campaign, "campaign_paused", "Campaign paused")
    return JsonResponse({"campaign": _serialize_campaign(campaign)})


@csrf_exempt
@require_POST
def resume_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign.objects.select_related("assigned_agent"), id=campaign_id)
    if campaign.status not in {CampaignStatus.PAUSED, CampaignStatus.DRAFT}:
        return JsonResponse({"error": "campaign cannot be resumed from current status"}, status=400)

    campaign.status = CampaignStatus.ACTIVE
    campaign.paused_at = None
    campaign.completed_at = None
    campaign.started_at = campaign.started_at or timezone.now()
    campaign.save(update_fields=["status", "paused_at", "completed_at", "started_at", "updated_at"])
    _set_campaign_cooldown_until(campaign, None)
    _log_campaign_event(campaign, "campaign_resumed", "Campaign resumed")

    dispatch = _dispatch_campaign_next_call(campaign)
    _log_campaign_event(campaign, "dispatch_result", "Dispatch attempted after resume", details=dispatch)
    campaign.refresh_from_db()
    return JsonResponse({"campaign": _serialize_campaign(campaign), "dispatch": dispatch})


@csrf_exempt
@require_POST
def stop_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)
    if campaign.status in {CampaignStatus.COMPLETED, CampaignStatus.ARCHIVED}:
        return JsonResponse({"campaign": _serialize_campaign(campaign)})

    campaign.status = CampaignStatus.ARCHIVED
    campaign.completed_at = campaign.completed_at or timezone.now()
    campaign.paused_at = timezone.now()
    campaign.save(update_fields=["status", "completed_at", "paused_at", "updated_at"])
    _log_campaign_event(campaign, "campaign_stopped", "Campaign stopped and archived")
    return JsonResponse({"campaign": _serialize_campaign(campaign)})


@csrf_exempt
@require_POST
def dispatch_campaign(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign.objects.select_related("assigned_agent"), id=campaign_id)
    dispatch = _dispatch_campaign_next_call(campaign)
    _log_campaign_event(campaign, "dispatch_result", "Manual dispatch requested", details=dispatch)
    campaign.refresh_from_db()
    return JsonResponse({"campaign": _serialize_campaign(campaign), "dispatch": dispatch})


@csrf_exempt
@require_POST
def campaign_tick(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign.objects.select_related("assigned_agent"), id=campaign_id)
    sync = _sync_campaign_open_calls(campaign, limit=20)
    recovery = _recover_stuck_in_progress_leads(campaign)
    dispatch = {"dispatched": False, "reason": "campaign_not_active"}

    campaign.refresh_from_db()
    if campaign.status == CampaignStatus.ACTIVE:
        dispatch = _dispatch_campaign_next_call(campaign)
        campaign.refresh_from_db()

    _log_campaign_event(
        campaign,
        "campaign_tick",
        "Campaign tick processed",
        details={"recovery": recovery, "sync": sync, "dispatch": dispatch},
    )

    return JsonResponse(
        {
            "campaign": _serialize_campaign(campaign),
            "recovery": recovery,
            "sync": sync,
            "dispatch": dispatch,
        }
    )


@csrf_exempt
@require_POST
def restart_campaign_from_first(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign.objects.select_related("assigned_agent"), id=campaign_id)
    payload = _load_json_body(request)
    start_now = _parse_bool(payload.get("start_now"), True)

    call_in_progress = CallSession.objects.filter(
        campaign_id=campaign.id,
    ).filter(
        _active_call_not_ended_filter(),
    ).filter(
        status__in=[
            CallStatus.QUEUED,
            CallStatus.DIALING,
            CallStatus.RINGING,
            CallStatus.BRIDGED,
            CallStatus.HUMAN_DETECTED,
            CallStatus.MACHINE_DETECTED,
        ],
    ).exists()
    if call_in_progress:
        return JsonResponse(
            {"error": "campaign_call_in_progress", "message": "Pause and wait for current call to end before restart"},
            status=409,
        )

    with transaction.atomic():
        rows = list(
            CampaignLead.objects.select_for_update()
            .filter(campaign=campaign)
            .order_by("queue_order", "id")
        )
        if not rows:
            return JsonResponse({"error": "campaign_queue_empty"}, status=400)

        lead_ids = []
        for index, row in enumerate(rows, start=1):
            row.queue_order = index
            row.status = CampaignLeadStatus.PENDING
            row.attempt_count = 0
            row.last_outcome = ""
            row.last_attempt_at = None
            row.next_attempt_at = None
            row.completed_at = None
            row.last_call_id = None
            lead_ids.append(row.lead_id)

        CampaignLead.objects.bulk_update(
            rows,
            [
                "queue_order",
                "status",
                "attempt_count",
                "last_outcome",
                "last_attempt_at",
                "next_attempt_at",
                "completed_at",
                "last_call",
            ],
        )

        LeadDialState.objects.filter(lead_id__in=lead_ids).update(
            attempt_count=0,
            last_attempt_at=None,
            next_attempt_at=None,
            last_outcome="",
            is_completed=False,
        )

        now = timezone.now()
        campaign.last_dispatch_at = None
        campaign.completed_at = None
        campaign.paused_at = None
        campaign.started_at = campaign.started_at or now
        campaign.status = CampaignStatus.ACTIVE if start_now else CampaignStatus.DRAFT
        campaign.save(
            update_fields=[
                "status",
                "started_at",
                "paused_at",
                "completed_at",
                "last_dispatch_at",
                "updated_at",
            ]
        )
        _set_campaign_cooldown_until(campaign, None)

    dispatch = {"dispatched": False, "reason": "not_started"}
    if start_now:
        dispatch = _dispatch_campaign_next_call(campaign)
    campaign.refresh_from_db()
    _log_campaign_event(
        campaign,
        "campaign_restarted_from_first",
        "Campaign reset to first contact",
        details={"start_now": start_now, "reset_contacts": len(rows), "dispatch": dispatch},
    )

    return JsonResponse(
        {
            "ok": True,
            "reset_contacts": len(rows),
            "campaign": _serialize_campaign(campaign),
            "dispatch": dispatch,
        }
    )


@csrf_exempt
def remove_campaign_contact(request: HttpRequest, campaign_id: int, lead_id: int) -> JsonResponse:
    if request.method not in {"POST", "DELETE"}:
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    campaign = get_object_or_404(Campaign, id=campaign_id)
    campaign_lead = (
        CampaignLead.objects.select_related("lead")
        .filter(campaign_id=campaign.id, lead_id=lead_id)
        .order_by("id")
        .first()
    )
    if not campaign_lead:
        return JsonResponse({"error": "contact_not_found_in_campaign"}, status=404)

    call_in_progress = CallSession.objects.filter(
        campaign_id=campaign.id,
        lead_id=lead_id,
    ).filter(
        _active_call_not_ended_filter(),
    ).filter(
        status__in=[
            CallStatus.QUEUED,
            CallStatus.DIALING,
            CallStatus.RINGING,
            CallStatus.BRIDGED,
            CallStatus.HUMAN_DETECTED,
            CallStatus.MACHINE_DETECTED,
        ],
    ).exists()
    if call_in_progress:
        return JsonResponse({"error": "contact_call_in_progress"}, status=409)

    removed = {
        "lead_id": campaign_lead.lead_id,
        "contact_name": campaign_lead.lead.full_name,
        "contact_phone": campaign_lead.lead.phone_e164,
    }
    campaign_lead.delete()
    _resequence_campaign_queue(campaign)
    _maybe_mark_campaign_completed(campaign)
    campaign.refresh_from_db()
    _log_campaign_event(
        campaign,
        "contact_removed",
        "Contact removed from campaign queue",
        details=removed,
        lead=campaign_lead.lead,
    )

    return JsonResponse(
        {
            "ok": True,
            "removed": removed,
            "campaign": _serialize_campaign(campaign),
        }
    )


@require_GET
def next_lead(request: HttpRequest) -> JsonResponse:
    # Simplified selection for V1: first non-completed lead state.
    dial_state = (
        LeadDialState.objects.select_related("lead")
        .filter(is_completed=False)
        .order_by("id")
        .first()
    )

    if not dial_state:
        return JsonResponse({"lead": None})

    lead = dial_state.lead
    return JsonResponse(
        {
            "lead": {
                "id": lead.id,
                "external_id": lead.external_id,
                "full_name": lead.full_name,
                "company_name": lead.company_name,
                "phone_e164": lead.phone_e164,
                "email": lead.email,
                "timezone": lead.timezone,
                "owner_hint": lead.owner_hint,
            }
        }
    )


@require_GET
def list_leads(request: HttpRequest) -> JsonResponse:
    page = _parse_positive_int(request.GET.get("page"), 1)
    page_size = _parse_positive_int(request.GET.get("page_size"), 20)
    page_size = max(1, min(page_size, 100))
    search = str(request.GET.get("search") or "").strip()
    campaign_filter = str(request.GET.get("campaign_id") or request.GET.get("campaign") or "").strip()

    queryset = Lead.objects.select_related("dial_state").order_by("-id")
    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search)
            | Q(phone_e164__icontains=search)
            | Q(company_name__icontains=search)
            | Q(email__icontains=search)
        )
    if campaign_filter:
        if campaign_filter.isdigit():
            queryset = queryset.filter(campaign_links__campaign_id=int(campaign_filter))
        else:
            queryset = queryset.filter(metadata__campaign_name=campaign_filter)

    queryset = queryset.distinct()

    count = queryset.count()
    offset = (page - 1) * page_size
    leads = list(queryset[offset : offset + page_size])

    results = [_serialize_lead_row(lead) for lead in leads]

    return JsonResponse({"count": count, "page": page, "page_size": page_size, "results": results})


@require_GET
def list_contacts(request: HttpRequest) -> JsonResponse:
    # Alias kept for frontend pages that still use /contacts/.
    return list_leads(request)


@csrf_exempt
@require_POST
def update_lead(request: HttpRequest, lead_id: int) -> JsonResponse:
    lead = get_object_or_404(Lead.objects.select_related("dial_state"), id=lead_id)

    active_call_exists = CallSession.objects.filter(
        lead_id=lead.id,
    ).filter(
        _active_call_not_ended_filter(),
    ).filter(
        status__in=[
            CallStatus.QUEUED,
            CallStatus.DIALING,
            CallStatus.RINGING,
            CallStatus.BRIDGED,
            CallStatus.HUMAN_DETECTED,
            CallStatus.MACHINE_DETECTED,
        ],
    ).exists()
    if active_call_exists:
        return JsonResponse({"error": "contact_call_in_progress"}, status=409)

    payload = _load_json_body(request)
    update_fields: list[str] = []

    full_name = str(payload.get("full_name") or "").strip()
    if full_name and full_name != lead.full_name:
        lead.full_name = full_name
        update_fields.append("full_name")

    raw_phone = payload.get("phone_e164")
    if raw_phone not in (None, ""):
        normalized_phone = _normalize_phone(raw_phone)
        if not normalized_phone:
            return JsonResponse({"error": "invalid_phone"}, status=400)
        if normalized_phone != lead.phone_e164:
            duplicate_exists = Lead.objects.filter(phone_e164=normalized_phone).exclude(id=lead.id).exists()
            if duplicate_exists:
                return JsonResponse({"error": "phone_already_exists"}, status=409)
            lead.phone_e164 = normalized_phone
            update_fields.append("phone_e164")

    for field_name in ("email", "company_name", "timezone", "owner_hint", "external_id"):
        if field_name in payload:
            value = str(payload.get(field_name) or "").strip()
            if getattr(lead, field_name) != value:
                setattr(lead, field_name, value)
                update_fields.append(field_name)

    if update_fields:
        lead.save(update_fields=list(dict.fromkeys(update_fields)))
        lead.refresh_from_db()

    return JsonResponse({"ok": True, "contact": _serialize_lead_row(lead)})


@csrf_exempt
@require_POST
def delete_lead(request: HttpRequest, lead_id: int) -> JsonResponse:
    result = _bulk_delete_lead_ids([lead_id])
    if lead_id in result.get("blocked_in_progress", []):
        return JsonResponse({"error": "contact_call_in_progress"}, status=409)
    if lead_id in result.get("blocked_with_history", []):
        return JsonResponse({"error": "contact_has_call_history"}, status=409)
    if lead_id in result.get("missing_ids", []):
        return JsonResponse({"error": "contact_not_found"}, status=404)

    deleted_rows = result.get("deleted_rows") or []
    contact_name = ""
    if deleted_rows:
        contact_name = str((deleted_rows[0] or {}).get("name") or "")
    return JsonResponse({"ok": True, "deleted": True, "lead_id": lead_id, "contact_name": contact_name})


@csrf_exempt
@require_POST
def bulk_delete_leads(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    lead_ids_payload = payload.get("lead_ids")
    if not isinstance(lead_ids_payload, list) or not lead_ids_payload:
        return JsonResponse({"error": "lead_ids list is required"}, status=400)

    lead_ids: list[int] = []
    for raw_id in lead_ids_payload:
        lead_id = _parse_positive_int(raw_id, 0)
        if lead_id > 0 and lead_id not in lead_ids:
            lead_ids.append(lead_id)

    if not lead_ids:
        return JsonResponse({"error": "no_valid_lead_ids"}, status=400)

    result = _bulk_delete_lead_ids(lead_ids)
    return JsonResponse({"ok": True, **result})


@csrf_exempt
@require_POST
def bulk_delete_filtered_leads(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    search = str(payload.get("search") or "").strip()
    campaign_filter = str(payload.get("campaign_id") or payload.get("campaign") or "").strip()
    force_all = _parse_bool(payload.get("force_all"), False)

    if not search and not campaign_filter and not force_all:
        return JsonResponse({"error": "filter_required"}, status=400)

    queryset = Lead.objects.order_by("-id")
    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search)
            | Q(phone_e164__icontains=search)
            | Q(company_name__icontains=search)
            | Q(email__icontains=search)
        )
    if campaign_filter:
        if campaign_filter.isdigit():
            queryset = queryset.filter(campaign_links__campaign_id=int(campaign_filter))
        else:
            queryset = queryset.filter(metadata__campaign_name=campaign_filter)

    lead_ids = list(queryset.distinct().values_list("id", flat=True))
    result = _bulk_delete_lead_ids(lead_ids)
    return JsonResponse(
        {
            "ok": True,
            "filter": {
                "search": search,
                "campaign": campaign_filter,
                "force_all": force_all,
            },
            **result,
        }
    )


@csrf_exempt
@require_POST
def upload_leads_csv(request: HttpRequest) -> JsonResponse:
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "csv file is required under 'file'"}, status=400)

    try:
        raw_bytes = upload.read()
        content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JsonResponse({"error": "unable to decode file as utf-8 csv"}, status=400)

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return JsonResponse({"error": "csv header row is missing"}, status=400)

    campaign_name = str(request.POST.get("campaign_name") or "").strip()
    campaign = None
    campaign_id = _parse_positive_int(request.POST.get("campaign_id"), 0)
    if campaign_id:
        campaign = Campaign.objects.filter(id=campaign_id).first()
        if not campaign:
            return JsonResponse({"error": "campaign_not_found"}, status=404)
        if not campaign_name:
            campaign_name = campaign.name

    campaign_settings = _extract_campaign_settings(request.POST)
    if campaign and not campaign_settings:
        campaign_settings = _campaign_settings_from_campaign(campaign)
    source_name = campaign_name or upload.name

    parsed_rows: list[dict] = []
    invalid_rows: list[dict] = []
    seen_upload_phones: set[str] = set()
    duplicate_in_file_count = 0

    for row_number, row in enumerate(reader, start=2):
        phone = _pick_value(
            row,
            ["phone_e164", "phone", "mobile", "phone_number", "contact_number", "number", "Phone", "Phone Number"],
        )
        phone = _normalize_phone(phone)

        if not phone:
            invalid_rows.append({"row": row_number, "reason": "missing_phone"})
            continue

        if phone in seen_upload_phones:
            duplicate_in_file_count += 1
            continue
        seen_upload_phones.add(phone)

        full_name = _pick_value(row, ["full_name", "name", "lead_name", "Name", "Full Name"]) or "Unknown Lead"
        email = _pick_value(row, ["email", "Email", "email_address"])
        company_name = _pick_value(row, ["company_name", "company", "Company", "organization", "deal_name", "Deal Name"]) or ""
        owner_hint = _pick_value(row, ["owner_hint", "owner", "agent", "sdr", "Owner", "designation", "Designation", "title", "job_title"]) or ""
        timezone_value = _pick_value(row, ["timezone", "tz", "Timezone"]) or "Asia/Kolkata"
        external_id = _pick_value(row, ["external_id", "id", "lead_id", "Lead ID"]) or ""

        row_metadata: dict[str, object] = {"raw_csv": row, "campaign_name": campaign_name}
        if campaign_settings:
            row_metadata["campaign_settings"] = campaign_settings

        parsed_rows.append(
            {
                "phone_e164": phone,
                "full_name": full_name,
                "email": email,
                "company_name": company_name,
                "owner_hint": owner_hint,
                "timezone": timezone_value,
                "external_id": external_id,
                "source_file": source_name,
                "metadata": row_metadata,
            }
        )

    if not parsed_rows:
        return JsonResponse(
            {
                "error": "no_valid_rows",
                "total_rows": len(invalid_rows),
                "invalid_count": len(invalid_rows),
                "invalid_rows": invalid_rows[:20],
            },
            status=400,
        )

    phones = [row["phone_e164"] for row in parsed_rows]
    existing_phone_set = set(Lead.objects.filter(phone_e164__in=phones).values_list("phone_e164", flat=True))

    leads_to_create = [
        Lead(
            external_id=row["external_id"],
            full_name=row["full_name"],
            company_name=row["company_name"],
            phone_e164=row["phone_e164"],
            email=row["email"],
            timezone=row["timezone"],
            owner_hint=row["owner_hint"],
            metadata=row["metadata"],
            source_file=row["source_file"],
        )
        for row in parsed_rows
        if row["phone_e164"] not in existing_phone_set
    ]

    if leads_to_create:
        Lead.objects.bulk_create(leads_to_create, batch_size=1000)

    all_leads = list(Lead.objects.filter(phone_e164__in=phones).only("id", "phone_e164"))
    lead_by_phone = {lead.phone_e164: lead for lead in all_leads}
    ordered_leads = [lead_by_phone[phone] for phone in phones if phone in lead_by_phone]

    existing_state_ids = set(
        LeadDialState.objects.filter(lead_id__in=[lead.id for lead in all_leads]).values_list("lead_id", flat=True)
    )
    states_to_create = [LeadDialState(lead=lead) for lead in all_leads if lead.id not in existing_state_ids]
    if states_to_create:
        LeadDialState.objects.bulk_create(states_to_create, batch_size=1000)

    created_count = len(leads_to_create)
    duplicate_existing_count = len(existing_phone_set)
    campaign_linked_count = 0
    campaign_already_linked_count = 0
    if campaign:
        campaign_linked_count, campaign_already_linked_count = _attach_leads_to_campaign(campaign, ordered_leads)
        if campaign_linked_count or campaign_already_linked_count:
            _log_campaign_event(
                campaign,
                "contacts_imported",
                "Contacts imported from CSV",
                details={
                    "created_count": created_count,
                    "campaign_linked_count": campaign_linked_count,
                    "campaign_already_linked_count": campaign_already_linked_count,
                },
            )

    return JsonResponse(
        {
            "ok": True,
            "file_name": upload.name,
            "campaign_name": campaign_name,
            "campaign_id": campaign.id if campaign else None,
            "total_rows": len(parsed_rows) + len(invalid_rows) + duplicate_in_file_count,
            "created_count": created_count,
            "duplicate_existing_count": duplicate_existing_count,
            "duplicate_in_file_count": duplicate_in_file_count,
            "invalid_count": len(invalid_rows),
            "invalid_rows": invalid_rows[:20],
            "campaign_linked_count": campaign_linked_count,
            "campaign_already_linked_count": campaign_already_linked_count,
        },
        status=201,
    )


@csrf_exempt
@require_POST
def create_manual_leads(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    campaign_name = str(payload.get("campaign_name") or "").strip()
    campaign = None
    campaign_id = _parse_positive_int(payload.get("campaign_id"), 0)
    if campaign_id:
        campaign = Campaign.objects.filter(id=campaign_id).first()
        if not campaign:
            return JsonResponse({"error": "campaign_not_found"}, status=404)
        if not campaign_name:
            campaign_name = campaign.name

    timezone_default = str(payload.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata"
    source_name = campaign_name or "manual-entry"
    metadata_payload = payload.get("metadata")
    metadata_source: dict[str, object] = {}
    for key in ("dialing_mode", "caller_id", "description", "delay_between_calls", "max_retries", "agent_id"):
        if key in payload:
            metadata_source[key] = payload.get(key)
    if isinstance(metadata_payload, dict):
        metadata_source.update(metadata_payload)
    campaign_settings = _extract_campaign_settings(metadata_source)
    if campaign and not campaign_settings:
        campaign_settings = _campaign_settings_from_campaign(campaign)

    leads_payload = payload.get("leads")
    if isinstance(leads_payload, list):
        rows = leads_payload
    else:
        rows = [payload]

    parsed_rows: list[dict] = []
    invalid_rows: list[dict] = []
    seen_upload_phones: set[str] = set()
    duplicate_in_payload_count = 0

    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            invalid_rows.append({"row": row_number, "reason": "invalid_lead_payload"})
            continue

        phone = _normalize_phone(
            _pick_value(
                row,
                ["phone_e164", "phone", "mobile", "phone_number", "contact_number", "number", "Phone", "Phone Number"],
            )
        )

        if not phone:
            invalid_rows.append({"row": row_number, "reason": "missing_phone"})
            continue

        if phone in seen_upload_phones:
            duplicate_in_payload_count += 1
            continue
        seen_upload_phones.add(phone)

        full_name = _pick_value(row, ["full_name", "name", "lead_name", "Name", "Full Name"]) or "Unknown Lead"
        email = _pick_value(row, ["email", "Email", "email_address"])
        company_name = _pick_value(row, ["company_name", "company", "Company", "organization", "deal_name", "Deal Name"]) or ""
        owner_hint = _pick_value(row, ["owner_hint", "owner", "agent", "sdr", "Owner", "designation", "Designation", "title", "job_title"]) or ""
        timezone_value = _pick_value(row, ["timezone", "tz", "Timezone"]) or timezone_default
        external_id = _pick_value(row, ["external_id", "id", "lead_id", "Lead ID"]) or ""

        row_metadata: dict[str, object] = {"raw_manual": row, "campaign_name": campaign_name}
        if campaign_settings:
            row_metadata["campaign_settings"] = campaign_settings

        parsed_rows.append(
            {
                "phone_e164": phone,
                "full_name": full_name,
                "email": email,
                "company_name": company_name,
                "owner_hint": owner_hint,
                "timezone": timezone_value,
                "external_id": external_id,
                "source_file": source_name,
                "metadata": row_metadata,
            }
        )

    if not parsed_rows:
        return JsonResponse(
            {
                "error": "no_valid_rows",
                "total_rows": len(invalid_rows),
                "invalid_count": len(invalid_rows),
                "invalid_rows": invalid_rows[:20],
            },
            status=400,
        )

    phones = [row["phone_e164"] for row in parsed_rows]
    existing_phone_set = set(Lead.objects.filter(phone_e164__in=phones).values_list("phone_e164", flat=True))

    leads_to_create = [
        Lead(
            external_id=row["external_id"],
            full_name=row["full_name"],
            company_name=row["company_name"],
            phone_e164=row["phone_e164"],
            email=row["email"],
            timezone=row["timezone"],
            owner_hint=row["owner_hint"],
            metadata=row["metadata"],
            source_file=row["source_file"],
        )
        for row in parsed_rows
        if row["phone_e164"] not in existing_phone_set
    ]

    if leads_to_create:
        Lead.objects.bulk_create(leads_to_create, batch_size=1000)

    all_leads = list(Lead.objects.filter(phone_e164__in=phones).only("id", "phone_e164"))
    existing_state_ids = set(
        LeadDialState.objects.filter(lead_id__in=[lead.id for lead in all_leads]).values_list("lead_id", flat=True)
    )
    states_to_create = [LeadDialState(lead=lead) for lead in all_leads if lead.id not in existing_state_ids]
    if states_to_create:
        LeadDialState.objects.bulk_create(states_to_create, batch_size=1000)

    created_count = len(leads_to_create)
    duplicate_existing_count = len(existing_phone_set)
    lead_by_phone = {lead.phone_e164: lead for lead in all_leads}
    ordered_leads = [lead_by_phone[phone] for phone in phones if phone in lead_by_phone]
    campaign_linked_count = 0
    campaign_already_linked_count = 0
    if campaign:
        campaign_linked_count, campaign_already_linked_count = _attach_leads_to_campaign(campaign, ordered_leads)
        if campaign_linked_count or campaign_already_linked_count:
            _log_campaign_event(
                campaign,
                "contacts_imported",
                "Contacts added manually",
                details={
                    "created_count": created_count,
                    "campaign_linked_count": campaign_linked_count,
                    "campaign_already_linked_count": campaign_already_linked_count,
                },
            )

    return JsonResponse(
        {
            "ok": True,
            "campaign_name": campaign_name,
            "campaign_id": campaign.id if campaign else None,
            "total_rows": len(parsed_rows) + len(invalid_rows) + duplicate_in_payload_count,
            "created_count": created_count,
            "duplicate_existing_count": duplicate_existing_count,
            "duplicate_in_payload_count": duplicate_in_payload_count,
            "invalid_count": len(invalid_rows),
            "invalid_rows": invalid_rows[:20],
            "campaign_linked_count": campaign_linked_count,
            "campaign_already_linked_count": campaign_already_linked_count,
        },
        status=201,
    )


@require_GET
def list_call_logs(request: HttpRequest) -> JsonResponse:
    page = _parse_positive_int(request.GET.get("page"), 1)
    page_size = 20
    search = str(request.GET.get("search") or "").strip()
    status_filter = str(request.GET.get("status") or "").strip().lower().replace("_", "-")
    campaign_filter = str(request.GET.get("campaign_id") or request.GET.get("campaign") or "").strip()
    call_id_filter = _parse_positive_int(request.GET.get("call_id"), 0)
    ordering = str(request.GET.get("ordering") or "-initiated_at").strip()
    include_raw = _parse_bool(request.GET.get("include_raw"), False)

    queryset = CallSession.objects.select_related(*_call_session_select_related_fields())

    if search:
        queryset = queryset.filter(
            Q(lead__full_name__icontains=search)
            | Q(lead__phone_e164__icontains=search)
            | Q(lead__company_name__icontains=search)
            | Q(agent__display_name__icontains=search)
            | Q(provider_call_uuid__icontains=search)
        )
    if campaign_filter and campaign_filter.isdigit():
        queryset = queryset.filter(campaign_id=int(campaign_filter))
    if call_id_filter:
        queryset = queryset.filter(id=call_id_filter)

    # Frontend sends "initiated_at"; map to model fields.
    if ordering in {"initiated_at", "created_at"}:
        queryset = queryset.order_by("started_at", "created_at")
    elif ordering in {"-initiated_at", "-created_at"}:
        queryset = queryset.order_by("-started_at", "-created_at")
    else:
        queryset = queryset.order_by("-created_at")

    all_calls = list(queryset)
    offset = (page - 1) * page_size
    page_calls = all_calls[offset : offset + page_size]

    # Keep list endpoint fast and deterministic: do not sync provider on plain refresh
    # unless caller explicitly asks for it.
    sync_exotel = _parse_bool(request.GET.get("sync_exotel"), False)
    if sync_exotel and page_calls:
        _sync_exotel_call_details(page_calls, max_fetch=20)
        for row in page_calls:
            row.refresh_from_db()

    results = [_serialize_call_log(call, include_raw=include_raw) for call in all_calls]
    summary_all = _build_call_logs_summary(results)

    if status_filter:
        results = [
            row
            for row in results
            if str(row.get("status", "")).strip().lower().replace("_", "-") == status_filter
        ]
    if campaign_filter and not campaign_filter.isdigit():
        campaign_name_filter = campaign_filter.strip().lower()
        results = [
            row
            for row in results
            if str(row.get("campaign_name", "")).strip().lower() == campaign_name_filter
        ]
    summary_filtered = _build_call_logs_summary(results)

    count = len(results)
    paged_results = results[offset : offset + page_size]

    return JsonResponse(
        {
            "count": count,
            "page": page,
            "page_size": page_size,
            "results": paged_results,
            "summary": summary_filtered,
            "summary_all": summary_all,
        }
    )


@require_GET
def list_recordings(request: HttpRequest) -> JsonResponse:
    page = _parse_positive_int(request.GET.get("page"), 1)
    page_size = max(1, min(_parse_positive_int(request.GET.get("page_size"), 25), 100))
    search = str(request.GET.get("search") or "").strip()
    source_filter = str(request.GET.get("source") or "").strip().lower()
    sync_exotel = _parse_bool(request.GET.get("sync_exotel"), False)
    sync_limit = max(1, min(_parse_positive_int(request.GET.get("sync_limit"), 120), 500))

    sync_result = _sync_recording_assets_from_exotel_calls(sync_exotel=sync_exotel, sync_limit=sync_limit)

    queryset = RecordingAsset.objects.select_related("call__lead", "call__agent").order_by("-created_at")
    if source_filter in {RecordingSource.EXOTEL, RecordingSource.UPLOAD}:
        queryset = queryset.filter(source=source_filter)
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(call__lead__full_name__icontains=search)
            | Q(call__lead__phone_e164__icontains=search)
            | Q(call__provider_call_uuid__icontains=search)
        )

    results = list(queryset)
    count = len(results)
    offset = (page - 1) * page_size
    paged = results[offset : offset + page_size]

    return JsonResponse(
        {
            "count": count,
            "page": page,
            "page_size": page_size,
            "results": [_serialize_recording_asset(recording, request=request, include_transcript=False) for recording in paged],
            "sync": sync_result,
        }
    )


@csrf_exempt
@require_POST
def upload_recording(request: HttpRequest) -> JsonResponse:
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "audio file is required under 'file'"}, status=400)

    file_size = int(getattr(upload, "size", 0) or 0)
    if file_size > RECORDING_UPLOAD_MAX_BYTES:
        return JsonResponse(
            {
                "error": "file_too_large",
                "max_bytes": RECORDING_UPLOAD_MAX_BYTES,
            },
            status=400,
        )

    original_name = str(getattr(upload, "name", "") or "recording").strip()
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if extension not in RECORDING_UPLOAD_ALLOWED_EXTENSIONS:
        return JsonResponse(
            {
                "error": "unsupported_file_type",
                "allowed_extensions": sorted(RECORDING_UPLOAD_ALLOWED_EXTENSIONS),
            },
            status=400,
        )

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name).strip("._")
    if not safe_name:
        safe_name = f"recording.{extension}"

    title = str(request.POST.get("title") or "").strip() or original_name
    recording = RecordingAsset(
        source=RecordingSource.UPLOAD,
        title=title[:255],
        transcript_status=TranscriptStatus.PROCESSING,
        transcript_error="",
    )
    recording.audio_file.save(f"{uuid4().hex}_{safe_name}", upload, save=False)
    recording.save()
    _set_recording_transcription_progress(
        recording,
        5,
        stage="queued",
        status=TranscriptStatus.PROCESSING,
    )

    try:
        uploaded_audio_path = str(recording.audio_file.path)
    except Exception:
        uploaded_audio_path = ""
    if uploaded_audio_path:
        inferred_duration = _extract_audio_duration_seconds_from_file(uploaded_audio_path)
        if inferred_duration and recording.duration_seconds != inferred_duration:
            recording.duration_seconds = inferred_duration
            recording.save(update_fields=["duration_seconds", "updated_at"])

    scheduled = _schedule_recording_auto_transcription(recording, reason="upload", force=True)
    if not scheduled:
        _mark_recording_transcription_failed(recording, "transcription_queue_unavailable")

    return JsonResponse(
        {
            "ok": True,
            "queued": bool(scheduled),
            "recording": _serialize_recording_asset(recording, request=request, include_transcript=True),
        },
        status=201,
    )


@require_GET
def get_recording(request: HttpRequest, recording_public_id: UUID) -> JsonResponse:
    recording = get_object_or_404(
        RecordingAsset.objects.select_related("call__lead", "call__agent"),
        public_id=recording_public_id,
    )

    if recording.call and recording.source == RecordingSource.EXOTEL:
        _upsert_recording_asset_from_call(recording.call)
        recording.refresh_from_db()

    if recording.transcript_status == TranscriptStatus.PROCESSING and _is_recording_transcription_processing_stale(recording):
        _mark_recording_transcription_failed(recording, "transcription_stale_timeout")
        recording.refresh_from_db()

    _schedule_recording_auto_transcription(recording, reason="recording_view")

    return JsonResponse(
        {
            "ok": True,
            "recording": _serialize_recording_asset(recording, request=request, include_transcript=True),
        }
    )


@csrf_exempt
@require_POST
def transcribe_recording(request: HttpRequest, recording_public_id: UUID) -> JsonResponse:
    recording = get_object_or_404(
        RecordingAsset.objects.select_related("call__lead", "call__agent"),
        public_id=recording_public_id,
    )
    language_override, invalid_language = _get_request_transcription_language(request)
    if invalid_language:
        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_transcription_language",
                "detail": "Use auto, en, or te.",
            },
            status=400,
        )
    if TRANSCRIPTION_ENGLISH_ONLY and language_override and not _is_english_language_code(language_override):
        return JsonResponse({"ok": False, "error": TRANSCRIPTION_NON_ENGLISH_ERROR}, status=400)
    language_for_job = None if TRANSCRIPTION_ENGLISH_ONLY else language_override

    if recording.call and recording.source == RecordingSource.EXOTEL:
        _upsert_recording_asset_from_call(recording.call)
        recording.refresh_from_db()
        if not _is_terminal_call_for_transcription(recording.call):
            return JsonResponse({"ok": False, "error": "recording_not_ready_for_transcription"}, status=409)

    if recording.transcript_status != TranscriptStatus.PROCESSING:
        recording.transcript_status = TranscriptStatus.PROCESSING
        recording.transcript_error = ""
        recording.save(update_fields=["transcript_status", "transcript_error", "updated_at"])
        _set_recording_transcription_progress(
            recording,
            5,
            stage="queued",
            status=TranscriptStatus.PROCESSING,
        )
        if recording.call:
            _save_call_transcript_payload(recording.call, TranscriptStatus.PROCESSING, "", [], error_text="")

    scheduled = _schedule_recording_auto_transcription(
        recording,
        reason="manual",
        force=True,
        language=language_for_job,
    )
    recording.refresh_from_db()
    return JsonResponse(
        {
            "ok": True,
            "queued": bool(scheduled or recording.transcript_status == TranscriptStatus.PROCESSING),
            "language": language_for_job or "auto",
            "recording": _serialize_recording_asset(recording, request=request, include_transcript=True),
            "segments_count": len(recording.transcript_segments) if isinstance(recording.transcript_segments, list) else 0,
        },
        status=202,
    )


@csrf_exempt
@require_GET
def get_call_session(request: HttpRequest, call_public_id: UUID) -> JsonResponse:
    call = get_object_or_404(
        CallSession.objects.select_related(*_call_session_select_related_fields()),
        public_id=call_public_id,
    )
    include_raw = _parse_bool(request.GET.get("include_raw"), False)
    sync_exotel = _parse_bool(request.GET.get("sync_exotel"), True)

    if sync_exotel and call.provider == ProviderType.EXOTEL and call.provider_call_uuid:
        _poll_single_exotel_call(call)
        call = CallSession.objects.select_related(*_call_session_select_related_fields()).get(id=call.id)
    if call.ended_at and not call.campaign_id:
        _sync_call_to_hubspot(call, reason="terminal", force=False)
        call = CallSession.objects.select_related(*_call_session_select_related_fields()).get(id=call.id)
    if call.recording_url:
        _maybe_schedule_call_recording_transcription(call, reason="call_session_view")

    return JsonResponse({"ok": True, "call": _serialize_call_log(call, include_raw=include_raw)})


@csrf_exempt
@require_POST
def hangup_call_session(request: HttpRequest, call_public_id: UUID) -> JsonResponse:
    call = get_object_or_404(
        CallSession.objects.select_related(*_call_session_select_related_fields()),
        public_id=call_public_id,
    )
    provider = get_provider()

    if call.provider == ProviderType.EXOTEL and isinstance(provider, ExotelProvider) and call.provider_call_uuid:
        provider.hangup(call.provider_call_uuid)

    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    raw_payload["manual_hangup_requested"] = {
        "at": timezone.now().isoformat(),
        "provider_call_uuid": call.provider_call_uuid,
    }
    call.raw_provider_payload = raw_payload
    call.save(update_fields=["raw_provider_payload"])

    call = CallSession.objects.select_related(*_call_session_select_related_fields()).get(id=call.id)
    return JsonResponse({"ok": True, "call": _serialize_call_log(call, include_raw=False)})


@csrf_exempt
@require_POST
def save_call_disposition(request: HttpRequest, call_public_id: UUID) -> JsonResponse:
    call = get_object_or_404(
        CallSession.objects.select_related(*_call_session_select_related_fields()),
        public_id=call_public_id,
    )
    payload = _load_json_body(request)
    outcome = str(payload.get("outcome") or "").strip().lower()
    notes = str(payload.get("notes") or "").strip()
    deal_id = _normalize_hubspot_deal_id(payload.get("deal_id"))
    deal_name = str(payload.get("deal_name") or "").strip()[:255]

    valid_outcomes = {choice[0] for choice in CallOutcome.choices}
    if outcome not in valid_outcomes:
        return JsonResponse(
            {
                "error": "invalid_outcome",
                "allowed_outcomes": sorted(valid_outcomes),
            },
            status=400,
        )

    if not _call_disposition_deal_fields_available(force_refresh=True):
        return JsonResponse(
            {"error": "call disposition schema is out of date. run: python manage.py migrate"},
            status=500,
        )

    user = getattr(request, "user", None)
    created_by = user if getattr(user, "is_authenticated", False) else None

    disposition_defaults: dict[str, object] = {
        "outcome": outcome,
        "notes": notes,
        "created_by": created_by,
    }
    if "deal_id" in payload:
        disposition_defaults["hubspot_deal_id"] = deal_id
    if "deal_name" in payload:
        disposition_defaults["hubspot_deal_name"] = deal_name

    disposition, _ = CallDisposition.objects.update_or_create(call=call, defaults=disposition_defaults)

    call = CallSession.objects.select_related(*_call_session_select_related_fields()).get(id=call.id)
    hubspot_sync = _sync_call_to_hubspot(
        call,
        reason="disposition",
        force=False,
        explicit_deal_id=deal_id if "deal_id" in payload else "",
        explicit_deal_name=deal_name if "deal_name" in payload else "",
    )
    call = CallSession.objects.select_related(*_call_session_select_related_fields()).get(id=call.id)
    return JsonResponse(
        {
            "ok": True,
            "disposition": {
                "outcome": disposition.outcome,
                "notes": disposition.notes,
                "deal_id": disposition.hubspot_deal_id,
                "deal_name": disposition.hubspot_deal_name,
                "created_at": disposition.created_at.isoformat() if disposition.created_at else None,
            },
            "hubspot_sync": hubspot_sync,
            "call": _serialize_call_log(call, include_raw=False),
        }
    )


@csrf_exempt
@require_POST
def sync_exotel_call_logs(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    limit = min(_parse_positive_int(payload.get("limit"), 50), 200)
    only_open = _parse_bool(payload.get("only_open"), True)
    campaign_id = _parse_positive_int(payload.get("campaign_id"), 0)

    provider = get_provider()
    if not isinstance(provider, ExotelProvider):
        return JsonResponse({"error": "TELEPHONY_PROVIDER must be set to exotel"}, status=400)
    if not provider.configured:
        return JsonResponse({"error": "exotel_not_configured"}, status=400)

    queryset = CallSession.objects.select_related("lead", "agent").filter(
        provider=ProviderType.EXOTEL
    ).exclude(provider_call_uuid="")
    if campaign_id:
        queryset = queryset.filter(campaign_id=campaign_id)
    if only_open:
        queryset = queryset.filter(ended_at__isnull=True)

    calls = list(queryset.order_by("-created_at")[:limit])
    sync_result = _sync_exotel_call_details(calls, max_fetch=limit)

    return JsonResponse(
        {
            "ok": True,
            "processed": len(calls),
            "synced": int(sync_result.get("synced") or 0),
            "updated": int(sync_result.get("updated") or 0),
            "failed_count": int(sync_result.get("failed_count") or 0),
            "failed": sync_result.get("failed") or [],
        }
    )


@csrf_exempt
@require_POST
def trigger_transcription(request: HttpRequest, call_id: int) -> JsonResponse:
    call = get_object_or_404(CallSession.objects.select_related("lead", "agent"), id=call_id)
    if not str(call.recording_url or "").strip():
        return JsonResponse({"ok": False, "error": "recording_not_available"}, status=400)

    recording, _ = _upsert_recording_asset_from_call(call)
    if not recording:
        return JsonResponse({"ok": False, "error": "recording_not_available"}, status=400)

    if recording.source == RecordingSource.EXOTEL and not _is_terminal_call_for_transcription(call):
        return JsonResponse({"ok": False, "error": "recording_not_ready_for_transcription"}, status=409)

    scheduled = _schedule_recording_auto_transcription(
        recording,
        reason="call_log_manual",
        force=True,
        language=None,
    )
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    if scheduled:
        raw_payload["transcript_status"] = "processing"
        raw_payload.pop("transcript_error", None)
    else:
        raw_payload["transcript_status"] = "failed"
        raw_payload["transcript_error"] = "transcription_queue_unavailable"
    call.raw_provider_payload = raw_payload
    call.save(update_fields=["raw_provider_payload"])
    return JsonResponse(
        {
            "ok": True,
            "call_id": call.id,
            "queued": bool(scheduled),
            "transcript_status": "processing" if scheduled else "failed",
            "error": "" if scheduled else "transcription_queue_unavailable",
        }
    )


@csrf_exempt
@require_POST
def start_exotel_call(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)

    lead_id = payload.get("lead_id")
    agent_id = payload.get("agent_id")
    agent_phone = payload.get("agent_phone")
    campaign_id = _parse_positive_int(payload.get("campaign_id"), 0)
    campaign = Campaign.objects.filter(id=campaign_id).first() if campaign_id else None

    if campaign:
        if not agent_id:
            agent_id = campaign.assigned_agent_id
        if not agent_phone:
            agent_phone = campaign.agent_phone

        active_campaign_call_exists = CallSession.objects.filter(
            campaign_id=campaign.id,
        ).filter(
            _active_call_not_ended_filter(),
        ).filter(
            status__in=[
                CallStatus.QUEUED,
                CallStatus.DIALING,
                CallStatus.RINGING,
                CallStatus.BRIDGED,
                CallStatus.HUMAN_DETECTED,
                CallStatus.MACHINE_DETECTED,
            ],
        ).exists()
        if active_campaign_call_exists:
            return JsonResponse(
                {"error": "campaign_call_in_progress", "message": "An active campaign call is already running"},
                status=409,
            )

    if not lead_id or not agent_id or not agent_phone:
        return JsonResponse(
            {"error": "lead_id, agent_id and agent_phone are required"},
            status=400,
        )

    lead = get_object_or_404(Lead, id=lead_id)
    agent = get_object_or_404(AgentProfile, id=agent_id)
    lead_metadata = lead.metadata if isinstance(lead.metadata, dict) else {}
    deal_id = _first_non_empty_text(
        _normalize_hubspot_deal_id(payload.get("deal_id")),
        _lookup_value(lead_metadata, ("deal_id", "dealId", "hubspot_deal_id", "hubspotDealId")),
    )
    deal_name = _first_non_empty_text(
        str(payload.get("deal_name") or "").strip()[:255],
        _lookup_value(lead_metadata, ("deal_name", "dealName", "hubspot_deal_name", "hubspotDealName")),
    )

    provider = get_provider()
    if not isinstance(provider, ExotelProvider):
        return JsonResponse(
            {"error": "TELEPHONY_PROVIDER must be set to exotel for this endpoint"},
            status=400,
        )

    callback_url = str(payload.get("status_callback_url") or "").strip()

    max_call_duration_seconds = _resolve_max_call_duration_seconds(
        payload.get("max_duration_seconds"),
    )
    if not callback_url:
        public_base = str(getattr(settings, "PUBLIC_WEBHOOK_BASE_URL", "") or "").strip().rstrip("/")
        if public_base:
            callback_url = f"{public_base}/api/v1/dialer/webhooks/exotel/"

    effective_wait_url = _assign_runtime_exotel_wait_url(provider)

    call = CallSession.objects.create(
        lead=lead,
        agent=agent,
        campaign=campaign,
        provider=ProviderType.EXOTEL,
        status=CallStatus.DIALING,
        started_at=timezone.now(),
        raw_provider_payload={
            "init_request": {
                "lead_id": lead.id,
                "agent_id": agent.id,
                "agent_phone": agent_phone,
                "lead_phone": lead.phone_e164,
                "campaign_id": campaign.id if campaign else None,
                "campaign_name": campaign.name if campaign else "",
                "dial_sequence": "lead_first",
                "max_duration_seconds": max_call_duration_seconds,
                "wait_audio_url": effective_wait_url,
                "deal_id": deal_id,
                "deal_name": deal_name,
                "metadata": {
                    "deal_id": deal_id,
                    "deal_name": deal_name,
                },
            }
        },
    )
    if campaign:
        _log_campaign_event(
            campaign,
            "call_start_requested",
            "Call start requested",
            details={"lead_id": lead.id, "agent_id": agent.id},
            call=call,
            lead=lead,
        )

    dial_request = DialRequest(
        lead_id=lead.id,
        # Dial lead first, then bridge to agent.
        from_number=lead.phone_e164,
        to_number=agent_phone,
        callback_url=callback_url,
        caller_id=str(
            payload.get("caller_id")
            or (campaign.caller_id if campaign else "")
            or os.getenv("EXOTEL_CALLER_ID", "")
        ).strip()
        or None,
        metadata={
            "call_public_id": str(call.public_id),
            "lead_id": lead.id,
            "agent_id": agent.id,
            "campaign_id": campaign.id if campaign else None,
        },
        max_duration_seconds=max_call_duration_seconds,
    )

    dial_response = provider.initiate_call(dial_request)
    if not dial_response.accepted:
        call.status = CallStatus.FAILED
        call.ended_at = timezone.now()
        call.raw_provider_payload = {
            "init_request": call.raw_provider_payload.get("init_request", {}),
            "init_response": dial_response.raw,
        }
        call.save(update_fields=["status", "ended_at", "raw_provider_payload"])
        if campaign:
            _log_campaign_event(
                campaign,
                "call_start_failed",
                "Manual campaign call rejected by provider",
                details={"error": "exotel_call_failed"},
                call=call,
                lead=lead,
            )
        return JsonResponse({"error": "exotel_call_failed", "details": dial_response.raw}, status=502)

    call.provider_call_uuid = dial_response.provider_call_id
    call.raw_provider_payload = {
        "init_request": call.raw_provider_payload.get("init_request", {}),
        "init_response": dial_response.raw,
    }
    call.save(update_fields=["provider_call_uuid", "raw_provider_payload"])

    agent.status = AgentStatus.BUSY
    agent.save(update_fields=["status", "last_state_change"])
    if campaign:
        _log_campaign_event(
            campaign,
            "call_started",
            "Manual campaign call initiated",
            details={"provider_call_uuid": call.provider_call_uuid},
            call=call,
            lead=lead,
        )

    return JsonResponse(
        {
            "call": {
                "id": str(call.public_id),
                "public_id": str(call.public_id),
                "numeric_id": call.id,
                "provider": call.provider,
                "provider_call_uuid": call.provider_call_uuid,
                "status": call.status,
            }
        },
        status=201,
    )


@csrf_exempt
@require_POST
def exotel_webhook(request: HttpRequest) -> JsonResponse:
    payload = _load_webhook_payload(request)
    _debug_runtime("webhook_received_payload", payload)
    provider = ExotelProvider()
    event = provider.parse_webhook(payload)
    _debug_runtime(
        "webhook_parsed_event",
        {
            "provider_call_id": event.provider_call_id,
            "event_type": event.event_type,
            "amd_result": event.amd_result,
        },
    )

    call: CallSession | None = None
    match_reason = ""
    if event.provider_call_id:
        call = (
            CallSession.objects.select_related("agent")
            .filter(provider=ProviderType.EXOTEL, provider_call_uuid=event.provider_call_id)
            .first()
        )
        if call:
            match_reason = "provider_call_uuid"

    if not call:
        call, match_reason = _match_call_from_webhook_payload(payload)

    if not call:
        logger.warning(
            "exotel_webhook_unknown_call provider_call_id=%s event_type=%s payload_keys=%s",
            event.provider_call_id,
            event.event_type,
            list(payload.keys())[:30] if isinstance(payload, dict) else [],
        )
        _debug_runtime(
            "webhook_unknown_call",
            {
                "provider_call_id": event.provider_call_id,
                "event_type": event.event_type,
                "payload_keys": list(payload.keys())[:30] if isinstance(payload, dict) else [],
            },
        )
        return JsonResponse({"ok": True, "ignored": "unknown_call", "provider_call_id": event.provider_call_id})

    now = timezone.now()
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    sid_switched: dict | None = None
    if event.provider_call_id:
        if not call.provider_call_uuid:
            call.provider_call_uuid = event.provider_call_id
        elif call.provider_call_uuid != event.provider_call_id:
            previous_call_uuid = call.provider_call_uuid
            aliases = raw_payload.get("provider_call_uuid_aliases", [])
            if not isinstance(aliases, list):
                aliases = []
            if call.provider_call_uuid not in aliases:
                aliases.append(call.provider_call_uuid)
            if event.provider_call_id not in aliases:
                aliases.append(event.provider_call_id)
            raw_payload["provider_call_uuid_aliases"] = aliases[-20:]
            # Promote to latest provider call id from webhook so future polling follows
            # the currently active leg/session id instead of stale initial id.
            call.provider_call_uuid = event.provider_call_id
            raw_payload["provider_call_uuid_last_switch"] = {
                "at": timezone.now().isoformat(),
                "from": previous_call_uuid,
                "to": event.provider_call_id,
            }
            sid_switched = {"from": previous_call_uuid, "to": event.provider_call_id}
    events = raw_payload.get("events", [])
    if not isinstance(events, list):
        events = []
    events.append(payload)
    raw_payload["events"] = events[-50:]
    raw_payload["last_event"] = payload
    raw_payload["webhook_call_match"] = match_reason or "unknown"
    call.raw_provider_payload = raw_payload

    update_fields = ["raw_provider_payload"]
    if call.provider_call_uuid:
        update_fields.append("provider_call_uuid")
    event_type = event.event_type.lower()
    payload_disposition = _extract_provider_disposition(payload)
    normalized_event = f"{event_type} {payload_disposition}".strip()
    amd = _normalize_amd(event.amd_result)

    if amd == "machine":
        call.status = CallStatus.MACHINE_DETECTED
        call.answered_at = call.answered_at or now
        call.ended_at = now
        update_fields.extend(["status", "answered_at", "ended_at"])

    if amd == "human":
        call.status = CallStatus.HUMAN_DETECTED
        call.answered_at = call.answered_at or now
        update_fields.extend(["status", "answered_at"])

    has_answered_signal = any(token in normalized_event for token in ("answered", "connected"))
    has_in_progress_signal = any(token in normalized_event for token in ("in-progress", "inprogress"))

    if has_answered_signal:
        call.status = CallStatus.BRIDGED
        call.answered_at = call.answered_at or now
        update_fields.extend(["status", "answered_at"])
    elif has_in_progress_signal and call.status in {CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING}:
        call.status = CallStatus.RINGING
        update_fields.append("status")

    terminal_event_tokens = (
        "terminal",
        "completed",
        "failed",
        "hangup",
        "disconnected",
        "busy",
        "no-answer",
        "no_answer",
        "canceled",
        "cancelled",
    )
    terminal_failed_outcomes = ("failed", "busy", "no-answer", "no_answer", "cancelled", "canceled")
    # Use explicit event/status signals only. Also ignore mixed "answered + terminal"
    # text until a clear terminal-only callback/poll confirms completion.
    has_terminal_token = any(token in event_type for token in terminal_event_tokens)
    has_answered_token = any(token in event_type for token in ("answered", "connected"))
    is_terminal_event = has_terminal_token and not has_answered_token

    if is_terminal_event:
        failed_terminal = payload_disposition in terminal_failed_outcomes or any(
            token in event_type for token in terminal_failed_outcomes
        )

        # Strict mode:
        # - Failed/machine events can finalize immediately.
        # - Successful terminal events are only recorded here; finalization waits for
        #   Exotel fetch_call() confirmation from poll/tick path.
        if amd == "machine":
            call.status = CallStatus.MACHINE_DETECTED
            call.ended_at = now
            call.wrap_up_deadline = now + timedelta(seconds=15)
            update_fields.extend(["status", "ended_at", "wrap_up_deadline"])
            if call.agent:
                call.agent.status = AgentStatus.WRAP_UP
                call.agent.save(update_fields=["status", "last_state_change"])
        elif failed_terminal:
            call.status = CallStatus.FAILED
            call.ended_at = now
            call.wrap_up_deadline = now + timedelta(seconds=15)
            update_fields.extend(["status", "ended_at", "wrap_up_deadline"])
            if call.agent:
                call.agent.status = AgentStatus.WRAP_UP
                call.agent.save(update_fields=["status", "last_state_change"])
        else:
            # Successful end is pending confirmation from Exotel call-details API.
            raw_payload["terminal_signal_waiting_confirmation"] = {
                "at": now.isoformat(),
                "event_type": event_type,
                "payload_disposition": payload_disposition,
            }
            call.raw_provider_payload = raw_payload
            update_fields.append("raw_provider_payload")

    call.save(update_fields=list(dict.fromkeys(update_fields)))
    _debug_runtime(
        "webhook_call_saved",
        {
            "call_id": call.id,
            "provider_call_uuid": call.provider_call_uuid,
            "status": call.status,
            "answered_at": call.answered_at.isoformat() if call.answered_at else None,
            "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            "is_terminal_event": is_terminal_event,
        },
    )

    if call.campaign_id and call.ended_at:
        _handle_campaign_call_terminal(call)
    elif call.campaign_id:
        campaign = Campaign.objects.filter(id=call.campaign_id).first()
        if campaign:
            if sid_switched:
                _log_campaign_event(
                    campaign,
                    "provider_call_sid_switched",
                    "Provider call SID switched from webhook",
                    details=sid_switched,
                    call=call,
                    lead=call.lead,
                )
            if is_terminal_event and not call.ended_at:
                _log_campaign_event(
                    campaign,
                    "terminal_waiting_provider_confirmation",
                    "Terminal webhook received; waiting for Exotel call-details confirmation",
                    details={"event_type": event_type, "status": call.status},
                    call=call,
                    lead=call.lead,
                )
            _log_campaign_event(
                campaign,
                "webhook_event",
                "Webhook event received",
                details={"event_type": event_type, "status": call.status, "amd": amd},
                call=call,
                lead=call.lead,
            )
    elif call.ended_at:
        _sync_call_to_hubspot(call, reason="terminal", force=False)

    return JsonResponse({"ok": True, "call_id": str(call.public_id), "status": call.status, "amd": amd})


def _campaign_settings_from_campaign(campaign: Campaign) -> dict:
    return {
        "dialing_mode": campaign.dialing_mode,
        "delay_between_calls": campaign.delay_between_calls,
        "max_retries": campaign.max_retries,
        "caller_id": campaign.caller_id,
        "agent_id": str(campaign.assigned_agent_id) if campaign.assigned_agent_id else "",
    }


def _attach_leads_to_campaign(campaign: Campaign, leads: list[Lead]) -> tuple[int, int]:
    if not leads:
        return 0, 0

    unique_leads: list[Lead] = []
    seen_ids: set[int] = set()
    for lead in leads:
        if not lead or not lead.id or lead.id in seen_ids:
            continue
        seen_ids.add(lead.id)
        unique_leads.append(lead)

    if not unique_leads:
        return 0, 0

    existing_ids = set(
        CampaignLead.objects.filter(campaign=campaign, lead_id__in=[lead.id for lead in unique_leads]).values_list(
            "lead_id", flat=True
        )
    )
    max_order = (
        CampaignLead.objects.filter(campaign=campaign).aggregate(max_order=Max("queue_order")).get("max_order") or 0
    )

    to_create = []
    for index, lead in enumerate(unique_leads, start=1):
        if lead.id in existing_ids:
            continue
        to_create.append(
            CampaignLead(
                campaign=campaign,
                lead=lead,
                queue_order=max_order + index,
                status=CampaignLeadStatus.PENDING,
            )
        )

    if to_create:
        CampaignLead.objects.bulk_create(to_create, batch_size=1000)

    return len(to_create), len(existing_ids)


def _serialize_campaign(campaign: Campaign) -> dict:
    queue = CampaignLead.objects.filter(campaign=campaign)
    total_contacts = queue.count()
    dialed_contacts = queue.filter(attempt_count__gt=0).count()
    pending_contacts = queue.filter(status=CampaignLeadStatus.PENDING).count()
    in_progress_contacts = queue.filter(status=CampaignLeadStatus.IN_PROGRESS).count()
    completed_contacts = queue.filter(status=CampaignLeadStatus.COMPLETED).count()
    failed_contacts = queue.filter(status=CampaignLeadStatus.FAILED).count()

    calls = list(CallSession.objects.select_related("lead", "agent").filter(campaign=campaign))
    rows = [_serialize_call_log(call) for call in calls]
    summary = _build_call_logs_summary(rows)
    connected_calls = int(summary.get("answered_calls") or 0)
    active_call = (
        CallSession.objects.select_related("lead", "agent")
        .filter(
            _active_call_not_ended_filter(),
            campaign=campaign,
            status__in=[
                CallStatus.QUEUED,
                CallStatus.DIALING,
                CallStatus.RINGING,
                CallStatus.BRIDGED,
                CallStatus.HUMAN_DETECTED,
                CallStatus.MACHINE_DETECTED,
            ],
        )
        .order_by("-created_at")
        .first()
    )
    active_call_in_progress = bool(active_call)
    active_call_summary = _serialize_active_campaign_call(active_call) if active_call else None

    now = timezone.now()
    next_dispatch_at = None
    cooldown_remaining_seconds = 0
    cooldown_until = _get_campaign_cooldown_until(campaign)
    if campaign.status == CampaignStatus.ACTIVE and cooldown_until and cooldown_until > now and not active_call_in_progress:
        next_dispatch_at = cooldown_until.isoformat()
        cooldown_remaining_seconds = max(1, int((cooldown_until - now).total_seconds()))

    progress_percentage = round((dialed_contacts / max(1, total_contacts)) * 100)
    connect_rate = round((connected_calls / max(1, total_contacts)) * 100, 1)

    agent = campaign.assigned_agent
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "status": campaign.status,
        "dialing_mode": campaign.dialing_mode,
        "agent_phone": campaign.agent_phone,
        "caller_id": campaign.caller_id,
        "delay_between_calls": campaign.delay_between_calls,
        "max_retries": campaign.max_retries,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "paused_at": campaign.paused_at.isoformat() if campaign.paused_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
        "total_contacts": total_contacts,
        "dialed_contacts": dialed_contacts,
        "connected_calls": connected_calls,
        "connect_rate": connect_rate,
        "progress_percentage": progress_percentage,
        "pending_contacts": pending_contacts,
        "in_progress_contacts": in_progress_contacts,
        "completed_contacts": completed_contacts,
        "failed_contacts": failed_contacts,
        "total_calls": int(summary.get("total_calls") or 0),
        "assigned_agent_id": campaign.assigned_agent_id,
        "assigned_agent_name": agent.display_name if agent else "Unassigned",
        "active_call_in_progress": active_call_in_progress,
        "active_call": active_call_summary,
        "next_dispatch_at": next_dispatch_at,
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "last_call_result": _get_campaign_last_call_result(campaign),
        "assigned_agent_details": {
            "id": agent.id,
            "full_name": agent.display_name,
            "display_name": agent.display_name,
            "status": agent.status,
        }
        if agent
        else None,
    }


def _serialize_active_campaign_call(call: CallSession | None) -> dict | None:
    if not call:
        return None

    now = timezone.now()
    started_at = call.started_at or call.created_at
    wait_seconds = _get_exotel_no_answer_wait_seconds()
    waiting_for_pickup = _is_call_waiting_for_customer_pickup(call)
    pickup_elapsed = 0
    pickup_left = 0
    if waiting_for_pickup and started_at:
        pickup_elapsed = max(0, int((now - started_at).total_seconds()))
        pickup_left = max(0, wait_seconds - pickup_elapsed)

    stage = "agent_in_call"
    if waiting_for_pickup:
        stage = "waiting_for_pickup"

    return {
        "call_id": call.id,
        "lead_id": call.lead_id,
        "contact_name": call.lead.full_name if call.lead else "",
        "contact_phone": call.lead.phone_e164 if call.lead else "",
        "agent_id": call.agent_id,
        "agent_name": call.agent.display_name if call.agent else "",
        "status": call.status,
        "display_status": _derive_display_status(call),
        "stage": stage,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "answered_at": call.answered_at.isoformat() if call.answered_at else None,
        "no_answer_wait_seconds": wait_seconds,
        "pickup_elapsed_seconds": pickup_elapsed,
        "pickup_seconds_left": pickup_left,
    }


def _resequence_campaign_queue(campaign: Campaign) -> None:
    rows = list(
        CampaignLead.objects.filter(campaign=campaign)
        .order_by("queue_order", "id")
        .only("id", "queue_order")
    )
    changed: list[CampaignLead] = []
    for index, row in enumerate(rows, start=1):
        if row.queue_order != index:
            row.queue_order = index
            changed.append(row)

    if changed:
        CampaignLead.objects.bulk_update(changed, ["queue_order"])


def _get_campaign_cooldown_until(campaign: Campaign) -> datetime | None:
    metadata = campaign.metadata if isinstance(campaign.metadata, dict) else {}
    value = metadata.get("cooldown_until")
    if not value:
        return None
    dt = _parse_provider_datetime(value)
    return dt


def _get_exotel_no_answer_wait_seconds() -> int:
    configured = int(getattr(settings, "EXOTEL_NO_ANSWER_WAIT_SECONDS", 60) or 60)
    return max(30, configured)


def _set_campaign_cooldown_until(campaign: Campaign, when: datetime | None) -> None:
    if not campaign or not campaign.id:
        return

    with transaction.atomic():
        locked_campaign = (
            Campaign.objects.select_for_update()
            .only("id", "metadata", "updated_at")
            .filter(id=campaign.id)
            .first()
        )
        if not locked_campaign:
            return

        metadata = locked_campaign.metadata if isinstance(locked_campaign.metadata, dict) else {}
        if when:
            metadata["cooldown_until"] = when.isoformat()
        else:
            metadata.pop("cooldown_until", None)

        locked_campaign.metadata = metadata
        locked_campaign.save(update_fields=["metadata", "updated_at"])

    campaign.metadata = metadata


def _set_campaign_last_call_result(campaign: Campaign, result: dict | None) -> None:
    if not campaign or not campaign.id:
        return

    with transaction.atomic():
        locked_campaign = (
            Campaign.objects.select_for_update()
            .only("id", "metadata", "updated_at")
            .filter(id=campaign.id)
            .first()
        )
        if not locked_campaign:
            return

        metadata = locked_campaign.metadata if isinstance(locked_campaign.metadata, dict) else {}
        if isinstance(result, dict):
            metadata["last_call_result"] = result
        else:
            metadata.pop("last_call_result", None)

        locked_campaign.metadata = metadata
        locked_campaign.save(update_fields=["metadata", "updated_at"])

    campaign.metadata = metadata


def _get_campaign_last_call_result(campaign: Campaign) -> dict | None:
    metadata = campaign.metadata if isinstance(campaign.metadata, dict) else {}
    value = metadata.get("last_call_result")
    if not isinstance(value, dict):
        return None
    return {
        "at": str(value.get("at") or ""),
        "display_status": str(value.get("display_status") or ""),
        "lead_id": value.get("lead_id"),
        "contact_name": str(value.get("contact_name") or ""),
        "call_id": value.get("call_id"),
    }


def _log_campaign_event(
    campaign: Campaign,
    event_type: str,
    message: str,
    *,
    details: dict | None = None,
    call: CallSession | None = None,
    lead: Lead | None = None,
) -> None:
    if not campaign or not campaign.id:
        return

    logger.info(
        "campaign_event campaign_id=%s type=%s message=%s details=%s call_id=%s lead_id=%s",
        campaign.id,
        str(event_type or "event"),
        str(message or ""),
        json.dumps(details if isinstance(details, dict) else {}, default=str),
        call.id if call else None,
        lead.id if lead else None,
    )


def _sync_campaign_open_calls(campaign: Campaign, limit: int = 20) -> dict:
    query = (
        CallSession.objects.select_related("campaign", "lead", "agent")
        .filter(campaign=campaign, provider=ProviderType.EXOTEL)
        .filter(_active_call_not_ended_filter())
        .exclude(provider_call_uuid="")
        .order_by("-created_at")
    )
    calls = list(query[: max(1, min(int(limit or 20), 100))])

    synced = 0
    updated = 0
    failed: list[dict] = []

    for call in calls:
        poll = _poll_single_exotel_call(call)
        if not poll.get("ok"):
            failed.append(
                {
                    "call_id": call.id,
                    "provider_call_uuid": call.provider_call_uuid,
                    "error": poll.get("error", "unknown_error"),
                }
            )
            continue

        changed = bool(poll.get("changed"))
        synced += 1
        call.refresh_from_db(
            fields=[
                "started_at",
                "created_at",
                "answered_at",
                "ended_at",
                "status",
                "campaign_id",
                "lead_id",
                "provider_call_uuid",
                "raw_provider_payload",
            ]
        )

        # Exotel-driven no-answer window:
        # keep the call active for up to 60s while customer may still pick up.
        # after timeout, mark as no-answer and move to next lead after campaign delay.
        if (
            not call.ended_at
            and _is_call_waiting_for_customer_pickup(call)
        ):
            started_at = call.started_at or call.created_at
            wait_seconds = _get_exotel_no_answer_wait_seconds()
            age_seconds = int((timezone.now() - started_at).total_seconds()) if started_at else 0
            if age_seconds >= wait_seconds:
                payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
                payload["no_answer_timeout"] = {
                    "at": timezone.now().isoformat(),
                    "age_seconds": age_seconds,
                    "wait_seconds": wait_seconds,
                    "disposition": "no-answer",
                }
                call.status = CallStatus.FAILED
                call.ended_at = timezone.now()
                call.raw_provider_payload = payload
                call.save(update_fields=["status", "ended_at", "raw_provider_payload"])

                provider = get_provider()
                if isinstance(provider, ExotelProvider):
                    provider.hangup(call.provider_call_uuid)

                changed = True
                _log_campaign_event(
                    campaign,
                    "call_no_answer_timeout",
                    "Call not answered within wait window; marked no-answer",
                    details={"call_id": call.id, "age_seconds": age_seconds, "wait_seconds": wait_seconds},
                    call=call,
                    lead=call.lead,
                )

        call.refresh_from_db(fields=["ended_at", "campaign_id"])
        if call.campaign_id and call.ended_at:
            _handle_campaign_call_terminal(call, auto_dispatch=False)
        if changed:
            updated += 1

    result = {
        "ok": True,
        "processed": len(calls),
        "synced": synced,
        "updated": updated,
        "failed_count": len(failed),
        "failed": failed[:25],
    }
    _log_campaign_event(campaign, "sync_result", "Open calls synced from provider", details=result)
    return result


def _sync_exotel_call_details(calls: list[CallSession], max_fetch: int = 20) -> dict:
    candidates = [
        call
        for call in calls
        if call.provider == ProviderType.EXOTEL and call.provider_call_uuid
    ][: max(1, min(int(max_fetch or 20), 100))]

    synced = 0
    updated = 0
    failed: list[dict] = []

    for call in candidates:
        poll = _poll_single_exotel_call(call)
        if not poll.get("ok"):
            failed.append(
                {
                    "call_id": call.id,
                    "provider_call_uuid": call.provider_call_uuid,
                    "error": poll.get("error", "unknown_error"),
                }
            )
            continue

        changed = bool(poll.get("changed"))
        synced += 1
        call.refresh_from_db()
        if call.ended_at:
            if call.campaign_id:
                _handle_campaign_call_terminal(call, auto_dispatch=False)
            else:
                _sync_call_to_hubspot(call, reason="terminal", force=False)
        if changed:
            updated += 1

    return {
        "ok": True,
        "processed": len(candidates),
        "synced": synced,
        "updated": updated,
        "failed_count": len(failed),
        "failed": failed[:25],
    }


def _poll_single_exotel_call(call: CallSession) -> dict:
    if not call or call.provider != ProviderType.EXOTEL or not call.provider_call_uuid:
        return {"ok": False, "error": "missing_exotel_call_reference"}

    # Fresh-call guard: Exotel can briefly return incomplete/stale state right after dial initiation.
    # Avoid premature terminal transitions during that window.
    min_sync_age_seconds = max(0, int(getattr(settings, "EXOTEL_MIN_SYNC_AGE_SECONDS", 12) or 12))
    if not call.ended_at and call.started_at and min_sync_age_seconds > 0:
        age_seconds = int((timezone.now() - call.started_at).total_seconds())
        if age_seconds < min_sync_age_seconds:
            return {
                "ok": True,
                "changed": False,
                "skipped": "fresh_call",
                "age_seconds": age_seconds,
                "min_sync_age_seconds": min_sync_age_seconds,
            }

    provider = get_provider()
    if not isinstance(provider, ExotelProvider):
        return {"ok": False, "error": "provider_not_supported"}
    if not provider.configured:
        return {"ok": False, "error": "exotel_not_configured"}

    result = provider.fetch_call(call.provider_call_uuid)
    _debug_runtime(
        "poll_fetch_call_result",
        {
            "call_id": call.id,
            "provider_call_uuid": call.provider_call_uuid,
            "ok": bool(result.get("ok")),
            "error": result.get("error"),
            "call": result.get("call"),
            "raw": result.get("raw"),
        },
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "unknown_error"), "raw": result.get("raw")}

    changed = _apply_exotel_snapshot(call, result.get("call") or {}, result.get("raw") or {})
    return {"ok": True, "changed": bool(changed)}


def _recover_stuck_in_progress_leads(campaign: Campaign) -> dict:
    rows = list(
        CampaignLead.objects.select_related("lead", "last_call")
        .filter(campaign=campaign, status=CampaignLeadStatus.IN_PROGRESS)
        .order_by("queue_order", "id")
    )
    if not rows:
        return {"checked": 0, "recovered_from_call": 0, "released_stale": 0}

    active_statuses = [
        CallStatus.QUEUED,
        CallStatus.DIALING,
        CallStatus.RINGING,
        CallStatus.BRIDGED,
        CallStatus.HUMAN_DETECTED,
        CallStatus.MACHINE_DETECTED,
    ]

    recovered_from_call = 0
    released_stale = 0

    for row in rows:
        handled_call_ids: set[int] = set()
        now = timezone.now()
        active_calls = list(
            CallSession.objects.select_related("lead")
            .filter(
                campaign=campaign,
                lead_id=row.lead_id,
                status__in=active_statuses,
            )
            .filter(_active_call_not_ended_filter())
            .order_by("-created_at")[:2]
        )
        has_active_call = bool(active_calls)

        if has_active_call:
            for active_call in active_calls:
                poll = _poll_single_exotel_call(active_call)
                if poll.get("ok"):
                    active_call.refresh_from_db(fields=["ended_at"])
                    if active_call.ended_at:
                        _handle_campaign_call_terminal(active_call, auto_dispatch=False)
                        recovered_from_call += 1
                        handled_call_ids.add(active_call.id)
                        continue
            has_active_call = CallSession.objects.filter(
                campaign=campaign,
                lead_id=row.lead_id,
                status__in=active_statuses,
            ).filter(_active_call_not_ended_filter()).exists()

        if has_active_call:
            continue

        if row.last_call_id and row.last_call_id not in handled_call_ids:
            last_call = row.last_call
            if last_call:
                last_call.refresh_from_db()
                if last_call.ended_at:
                    _handle_campaign_call_terminal(last_call, auto_dispatch=False)
                    recovered_from_call += 1
                    continue
                if last_call.status in {CallStatus.FAILED, CallStatus.MACHINE_DETECTED}:
                    # Exotel can send terminal failed/machine status without end timestamp.
                    last_call.ended_at = now
                    last_call.save(update_fields=["ended_at"])
                    _handle_campaign_call_terminal(last_call, auto_dispatch=False)
                    recovered_from_call += 1
                    continue

    if recovered_from_call or released_stale:
        _log_campaign_event(
            campaign,
            "recovered_in_progress",
            "Recovered stuck in-progress contacts",
            details={
                "checked": len(rows),
                "recovered_from_call": recovered_from_call,
                "released_stale": released_stale,
                "stale_after_seconds": 0,
            },
        )

    return {
        "checked": len(rows),
        "recovered_from_call": recovered_from_call,
        "released_stale": released_stale,
    }


def _dispatch_campaign_next_call(campaign: Campaign) -> dict:
    lock_key = f"dialer:campaign_dispatch_lock:{campaign.id}"
    lock_token = str(uuid4())
    lock_acquired = cache.add(lock_key, lock_token, timeout=60)
    if not lock_acquired:
        result = {"dispatched": False, "reason": "dispatch_locked"}
        _log_campaign_event(campaign, "dispatch_blocked", "Dispatch lock is active", details=result)
        return result

    try:
        campaign = Campaign.objects.filter(id=campaign.id).first() or campaign
        if campaign.status != CampaignStatus.ACTIVE:
            result = {"dispatched": False, "reason": "campaign_not_active"}
            _log_campaign_event(campaign, "dispatch_blocked", "Campaign is not active", details=result)
            return result

        with transaction.atomic():
            # Hard serialize dispatch per campaign at DB level so concurrent tick/webhook/retry
            # requests can never pick multiple leads at once.
            locked_campaign = Campaign.objects.select_for_update().filter(id=campaign.id).first()
            if not locked_campaign:
                result = {"dispatched": False, "reason": "campaign_not_found"}
                _log_campaign_event(campaign, "dispatch_blocked", "Campaign not found during dispatch", details=result)
                return result
            campaign = locked_campaign

            if campaign.status != CampaignStatus.ACTIVE:
                result = {"dispatched": False, "reason": "campaign_not_active"}
                _log_campaign_event(campaign, "dispatch_blocked", "Campaign is not active", details=result)
                return result
            if campaign.dialing_mode != CampaignDialingMode.POWER:
                result = {"dispatched": False, "reason": "dialing_mode_not_supported"}
                _log_campaign_event(campaign, "dispatch_blocked", "Dialing mode is not power dialer", details=result)
                return result
            if not campaign.assigned_agent_id:
                result = {"dispatched": False, "reason": "missing_assigned_agent"}
                _log_campaign_event(campaign, "dispatch_blocked", "Assigned agent is missing", details=result)
                return result
            if not campaign.agent_phone:
                result = {"dispatched": False, "reason": "missing_agent_phone"}
                _log_campaign_event(campaign, "dispatch_blocked", "Agent phone is missing", details=result)
                return result

            now = timezone.now()
            cooldown_until = _get_campaign_cooldown_until(campaign)
            if cooldown_until and now < cooldown_until:
                result = {
                    "dispatched": False,
                    "reason": "cooldown_active",
                    "retry_after_seconds": max(1, int((cooldown_until - now).total_seconds())),
                    "next_dispatch_at": cooldown_until.isoformat(),
                }
                _log_campaign_event(campaign, "dispatch_blocked", "Cooldown active", details=result)
                return result

            in_progress_exists = CampaignLead.objects.filter(
                campaign_id=campaign.id,
                status=CampaignLeadStatus.IN_PROGRESS,
            ).exists()
            if in_progress_exists:
                result = {"dispatched": False, "reason": "lead_in_progress"}
                _log_campaign_event(campaign, "dispatch_blocked", "A lead is still in progress", details=result)
                return result

            in_flight = CallSession.objects.filter(
                campaign_id=campaign.id,
            ).filter(
                _active_call_not_ended_filter(),
            ).filter(
                status__in=[
                    CallStatus.QUEUED,
                    CallStatus.DIALING,
                    CallStatus.RINGING,
                    CallStatus.BRIDGED,
                    CallStatus.HUMAN_DETECTED,
                    CallStatus.MACHINE_DETECTED,
                ],
            ).exists()
            if in_flight:
                result = {"dispatched": False, "reason": "call_in_progress"}
                _log_campaign_event(campaign, "dispatch_blocked", "A call is still in progress", details=result)
                return result

            campaign_lead = (
                CampaignLead.objects.select_for_update(skip_locked=True)
                .select_related("lead")
                .filter(campaign_id=campaign.id, status=CampaignLeadStatus.PENDING)
                .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
                .order_by("queue_order", "id")
                .first()
            )

            if not campaign_lead:
                _maybe_mark_campaign_completed(campaign)
                result = {"dispatched": False, "reason": "queue_empty"}
                _log_campaign_event(campaign, "dispatch_blocked", "No pending contacts in queue", details=result)
                return result

            campaign_lead.status = CampaignLeadStatus.IN_PROGRESS
            campaign_lead.attempt_count += 1
            campaign_lead.last_attempt_at = now
            campaign_lead.next_attempt_at = None
            campaign_lead.save(update_fields=["status", "attempt_count", "last_attempt_at", "next_attempt_at", "updated_at"])

        try:
            dispatch_result = _initiate_campaign_call(campaign, campaign_lead)
        except Exception as exc:
            logger.exception(
                "campaign_dispatch_exception campaign_id=%s campaign_lead_id=%s",
                campaign.id,
                campaign_lead.id,
            )
            dispatch_result = {"accepted": False, "error": str(exc) or "dispatch_exception"}

        if dispatch_result.get("accepted"):
            result = {
                "dispatched": True,
                "campaign_lead_id": campaign_lead.id,
                "lead_id": campaign_lead.lead_id,
                "call_id": dispatch_result.get("call_id"),
                "provider_call_uuid": dispatch_result.get("provider_call_uuid"),
            }
            _log_campaign_event(
                campaign,
                "dispatch_success",
                "Contact dispatched for calling",
                details=result,
                lead=campaign_lead.lead,
            )
            return result

        campaign_lead.refresh_from_db(fields=["status", "next_attempt_at", "completed_at"])
        if campaign_lead.status == CampaignLeadStatus.IN_PROGRESS:
            retry_delay = max(15, int(campaign.delay_between_calls or 15))
            campaign_lead.status = CampaignLeadStatus.PENDING
            campaign_lead.next_attempt_at = timezone.now() + timedelta(seconds=retry_delay)
            campaign_lead.completed_at = None
            campaign_lead.save(update_fields=["status", "next_attempt_at", "completed_at", "updated_at"])

        result = {
            "dispatched": False,
            "reason": str(dispatch_result.get("error") or "unable_to_dispatch"),
            "details": dispatch_result,
            "campaign_lead_id": campaign_lead.id,
            "lead_id": campaign_lead.lead_id,
        }
        _log_campaign_event(campaign, "dispatch_failed", "Unable to dispatch contact", details=result)
        return result
    finally:
        current_token = cache.get(lock_key)
        if current_token == lock_token:
            cache.delete(lock_key)


def _initiate_campaign_call(campaign: Campaign, campaign_lead: CampaignLead) -> dict:
    lead = campaign_lead.lead
    agent = campaign.assigned_agent
    if not lead or not agent:
        result = {"accepted": False, "error": "missing_lead_or_agent"}
        _log_campaign_event(campaign, "call_start_failed", "Missing lead or agent", details=result)
        return result

    provider = get_provider()
    if not isinstance(provider, ExotelProvider):
        campaign_lead.status = CampaignLeadStatus.FAILED
        campaign_lead.last_outcome = "failed"
        campaign_lead.completed_at = timezone.now()
        campaign_lead.save(update_fields=["status", "last_outcome", "completed_at", "updated_at"])
        result = {"accepted": False, "error": "provider_not_supported"}
        _log_campaign_event(campaign, "call_start_failed", "Provider not supported", details=result, lead=lead)
        return result

    callback_url = str(getattr(settings, "PUBLIC_WEBHOOK_BASE_URL", "") or "").strip().rstrip("/")
    callback_url = f"{callback_url}/api/v1/dialer/webhooks/exotel/" if callback_url else ""

    effective_wait_url = _assign_runtime_exotel_wait_url(provider)
    lead_metadata = lead.metadata if isinstance(lead.metadata, dict) else {}
    deal_id = _normalize_hubspot_deal_id(
        _lookup_value(lead_metadata, ("deal_id", "dealId", "hubspot_deal_id", "hubspotDealId"))
    )
    deal_name = _lookup_value(lead_metadata, ("deal_name", "dealName", "hubspot_deal_name", "hubspotDealName"))

    max_call_duration_seconds = _resolve_max_call_duration_seconds()
    call = CallSession.objects.create(
        lead=lead,
        agent=agent,
        campaign=campaign,
        provider=ProviderType.EXOTEL,
        status=CallStatus.DIALING,
        started_at=timezone.now(),
        raw_provider_payload={
            "init_request": {
                "lead_id": lead.id,
                "agent_id": agent.id,
                "agent_phone": campaign.agent_phone,
                "lead_phone": lead.phone_e164,
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "dial_sequence": "lead_first",
                "max_duration_seconds": max_call_duration_seconds,
                "wait_audio_url": effective_wait_url,
                "deal_id": deal_id,
                "deal_name": deal_name,
                "metadata": {
                    "deal_id": deal_id,
                    "deal_name": deal_name,
                },
            }
        },
    )
    # Link call immediately so recovery never treats this row as call-less in-progress.
    campaign_lead.last_call = call
    campaign_lead.save(update_fields=["last_call", "updated_at"])

    dial_response = provider.initiate_call(
        DialRequest(
            lead_id=lead.id,
            from_number=lead.phone_e164,
            to_number=campaign.agent_phone,
            callback_url=callback_url,
            caller_id=campaign.caller_id or os.getenv("EXOTEL_CALLER_ID", "") or None,
            metadata={
                "call_public_id": str(call.public_id),
                "lead_id": lead.id,
                "agent_id": agent.id,
                "campaign_id": campaign.id,
            },
            max_duration_seconds=max_call_duration_seconds,
        )
    )

    if not dial_response.accepted:
        call.status = CallStatus.FAILED
        call.ended_at = timezone.now()
        call.raw_provider_payload = {
            "init_request": call.raw_provider_payload.get("init_request", {}),
            "init_response": dial_response.raw,
        }
        call.save(update_fields=["status", "ended_at", "raw_provider_payload"])

        _handle_campaign_call_terminal(call, auto_dispatch=False)
        result = {"accepted": False, "error": "exotel_call_failed", "details": dial_response.raw}
        _log_campaign_event(campaign, "call_start_failed", "Provider rejected call", details=result, call=call, lead=lead)
        return result

    call.provider_call_uuid = dial_response.provider_call_id
    call.raw_provider_payload = {
        "init_request": call.raw_provider_payload.get("init_request", {}),
        "init_response": dial_response.raw,
    }
    call.save(update_fields=["provider_call_uuid", "raw_provider_payload"])

    campaign.last_dispatch_at = timezone.now()
    campaign.save(update_fields=["last_dispatch_at", "updated_at"])
    _set_campaign_cooldown_until(campaign, None)
    _set_campaign_last_call_result(campaign, None)

    if agent.status != AgentStatus.BUSY:
        agent.status = AgentStatus.BUSY
        agent.save(update_fields=["status", "last_state_change"])

    result = {"accepted": True, "call_id": call.id, "provider_call_uuid": call.provider_call_uuid}
    _log_campaign_event(campaign, "call_started", "Call initiated with provider", details=result, call=call, lead=lead)
    return result


def _handle_campaign_call_terminal(call: CallSession, auto_dispatch: bool = False) -> None:
    should_dispatch = False
    campaign_for_dispatch = None

    with transaction.atomic():
        call = (
            CallSession.objects.select_for_update()
            .filter(id=call.id)
            .first()
        )
        if not call:
            return

        campaign = call.campaign
        if not campaign:
            return

        raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
        # Prevent duplicate terminal processing for the same call (e.g. webhook + poll sync).
        if raw_payload.get("campaign_terminal_processed"):
            return

        campaign_lead = (
            CampaignLead.objects.select_related("campaign", "lead")
            .select_for_update()
            .filter(campaign_id=campaign.id, lead_id=call.lead_id)
            .order_by("id")
            .first()
        )
        if not campaign_lead:
            return

        # Already finalized for this call/lead; avoid duplicate terminal processing.
        if campaign_lead.last_call_id == call.id and campaign_lead.status != CampaignLeadStatus.IN_PROGRESS:
            return

        now = timezone.now()
        display_status = _derive_display_status(call)
        success_statuses = {"answered", "completed"}
        retry_delay = max(15, int(campaign.delay_between_calls or 15))
        max_retries = max(0, int(campaign.max_retries or 0))

        # Strict success confirmation:
        # if a call looks "answered/completed" but provider hasn't given reliable end signal yet,
        # do not advance queue.
        if display_status in success_statuses:
            duration_seconds = _duration_seconds_for_call(call)
            provider_end_confirmed = _has_provider_end_confirmation(call, raw_payload)
            end_confirmed = bool(
                call.ended_at and (provider_end_confirmed or (duration_seconds is not None and duration_seconds > 0))
            )
            if not end_confirmed:
                started_at = call.answered_at or call.started_at or call.created_at
                age_seconds = int((now - started_at).total_seconds()) if started_at else 0
                raw_payload["campaign_terminal_deferred"] = {
                    "at": now.isoformat(),
                    "display_status": display_status,
                    "duration_seconds": duration_seconds,
                    "provider_end_confirmed": provider_end_confirmed,
                    "age_seconds": age_seconds,
                    "reason": "awaiting_provider_end_confirmation",
                }
                call.raw_provider_payload = raw_payload
                if call.ended_at:
                    # Re-open until provider confirmation arrives so sync keeps polling this call.
                    call.ended_at = None
                    call.save(update_fields=["ended_at", "raw_provider_payload"])
                else:
                    call.save(update_fields=["raw_provider_payload"])
                _log_campaign_event(
                    campaign,
                    "terminal_deferred",
                    "Terminal processing deferred until provider confirms end",
                    details={
                        "display_status": display_status,
                        "duration_seconds": duration_seconds,
                        "provider_end_confirmed": provider_end_confirmed,
                        "age_seconds": age_seconds,
                    },
                    call=call,
                    lead=call.lead,
                )
                return

        raw_payload["campaign_terminal_processed"] = True
        raw_payload["campaign_terminal_processed_at"] = now.isoformat()
        call.raw_provider_payload = raw_payload
        call.save(update_fields=["raw_provider_payload"])

        campaign_lead.last_call = call
        campaign_lead.last_outcome = display_status

        if display_status in success_statuses:
            campaign_lead.status = CampaignLeadStatus.COMPLETED
            campaign_lead.completed_at = now
            campaign_lead.next_attempt_at = None
        else:
            if display_status in {"no-answer", "sdr-cut"}:
                # Product requirement: negative terminal outcomes should move to next contact (no retry).
                campaign_lead.status = CampaignLeadStatus.FAILED
                campaign_lead.completed_at = now
                campaign_lead.next_attempt_at = None
            elif campaign_lead.attempt_count <= max_retries and campaign.status not in {CampaignStatus.ARCHIVED, CampaignStatus.COMPLETED}:
                campaign_lead.status = CampaignLeadStatus.PENDING
                campaign_lead.next_attempt_at = now + timedelta(seconds=retry_delay)
                campaign_lead.completed_at = None
            else:
                campaign_lead.status = CampaignLeadStatus.FAILED
                campaign_lead.completed_at = now
                campaign_lead.next_attempt_at = None

        campaign_lead.save(
            update_fields=[
                "last_call",
                "last_outcome",
                "status",
                "next_attempt_at",
                "completed_at",
                "updated_at",
            ]
        )

        dial_state, _ = LeadDialState.objects.get_or_create(lead=call.lead)
        dial_state.attempt_count = max(dial_state.attempt_count, campaign_lead.attempt_count)
        dial_state.last_attempt_at = now
        mapped_outcome = _to_call_outcome(display_status)
        if mapped_outcome:
            dial_state.last_outcome = mapped_outcome
        dial_state.is_completed = display_status in success_statuses
        dial_state.save(update_fields=["attempt_count", "last_attempt_at", "last_outcome", "is_completed"])

        if call.agent and call.agent.status in {AgentStatus.BUSY, AgentStatus.RINGING, AgentStatus.WRAP_UP}:
            call.agent.status = AgentStatus.AVAILABLE
            call.agent.save(update_fields=["status", "last_state_change"])

        _maybe_mark_campaign_completed(campaign)
        campaign.last_dispatch_at = now
        campaign.save(update_fields=["last_dispatch_at", "updated_at"])
        delay_seconds = max(15, int(campaign.delay_between_calls or 15))
        _set_campaign_cooldown_until(campaign, now + timedelta(seconds=delay_seconds) if delay_seconds > 0 else None)
        _set_campaign_last_call_result(
            campaign,
            {
                "at": now.isoformat(),
                "display_status": display_status,
                "lead_id": call.lead_id,
                "contact_name": call.lead.full_name if call.lead else "",
                "call_id": call.id,
            },
        )
        _log_campaign_event(
            campaign,
            "call_terminal_processed",
            "Terminal call processed and queue updated",
            details={
                "display_status": display_status,
                "campaign_lead_status": campaign_lead.status,
                "attempt_count": campaign_lead.attempt_count,
                "next_attempt_at": campaign_lead.next_attempt_at.isoformat() if campaign_lead.next_attempt_at else None,
            },
            call=call,
            lead=call.lead,
        )
        campaign_for_dispatch = campaign
        should_dispatch = bool(auto_dispatch and campaign.status == CampaignStatus.ACTIVE)

    hubspot_sync_result = _sync_call_to_hubspot(call, reason="terminal", force=False)
    if not hubspot_sync_result.get("ok") and not hubspot_sync_result.get("skipped"):
        logger.warning(
            "hubspot_sync_failed call_id=%s campaign_id=%s error=%s",
            call.id,
            call.campaign_id,
            hubspot_sync_result.get("error"),
        )

    if should_dispatch and campaign_for_dispatch:
        _log_campaign_event(
            campaign_for_dispatch,
            "call_terminal",
            "Call reached terminal state; attempting next dispatch",
            details={"call_id": call.id, "status": call.status},
            call=call,
            lead=call.lead,
        )
        dispatch_result = _dispatch_campaign_next_call(campaign_for_dispatch)
        if not dispatch_result.get("dispatched") and dispatch_result.get("reason") == "cooldown_active":
            retry_after = max(1, int(dispatch_result.get("retry_after_seconds") or 1))
            _schedule_campaign_dispatch_retry(
                campaign_for_dispatch.id,
                retry_after + 1,
                reason="cooldown_after_terminal",
            )
        elif not dispatch_result.get("dispatched") and dispatch_result.get("reason") == "dispatch_locked":
            _schedule_campaign_dispatch_retry(
                campaign_for_dispatch.id,
                2,
                reason="dispatch_lock_after_terminal",
            )


def _maybe_mark_campaign_completed(campaign: Campaign) -> None:
    has_open = CampaignLead.objects.filter(
        campaign=campaign, status__in=[CampaignLeadStatus.PENDING, CampaignLeadStatus.IN_PROGRESS]
    ).exists()
    if has_open:
        return

    live_call_exists = CallSession.objects.filter(
        campaign=campaign,
    ).filter(
        _active_call_not_ended_filter(),
    ).filter(
        status__in=[CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING, CallStatus.BRIDGED, CallStatus.HUMAN_DETECTED],
    ).exists()
    if live_call_exists:
        return

    if campaign.status != CampaignStatus.COMPLETED:
        campaign.status = CampaignStatus.COMPLETED
        campaign.completed_at = campaign.completed_at or timezone.now()
        campaign.save(update_fields=["status", "completed_at", "updated_at"])
        _log_campaign_event(campaign, "campaign_completed", "Campaign marked completed")


def _schedule_campaign_dispatch_retry(campaign_id: int, delay_seconds: int, reason: str = "") -> None:
    delay = max(1, min(int(delay_seconds or 1), 300))
    schedule_key = f"dialer:campaign_dispatch_retry:{campaign_id}"
    schedule_token = f"{timezone.now().isoformat()}:{delay}:{reason or 'retry'}"
    if not cache.add(schedule_key, schedule_token, timeout=delay + 30):
        return

    def _retry() -> None:
        try:
            campaign = Campaign.objects.select_related("assigned_agent").filter(id=campaign_id).first()
            if not campaign or campaign.status != CampaignStatus.ACTIVE:
                return
            dispatch = _dispatch_campaign_next_call(campaign)
            _log_campaign_event(
                campaign,
                "dispatch_retry",
                "Scheduled dispatch retry attempted",
                details={
                    "reason": reason or "retry",
                    "delay_seconds": delay,
                    "dispatch": dispatch,
                },
            )
            if not dispatch.get("dispatched") and dispatch.get("reason") in {"cooldown_active", "dispatch_locked"}:
                retry_after = max(1, int(dispatch.get("retry_after_seconds") or 2))
                next_delay = retry_after + 1 if dispatch.get("reason") == "cooldown_active" else 2
                cache.delete(schedule_key)
                _schedule_campaign_dispatch_retry(
                    campaign.id,
                    next_delay,
                    reason=f"{reason or 'retry'}:{dispatch.get('reason')}",
                )
        except Exception:
            logger.exception("scheduled dispatch retry failed for campaign_id=%s", campaign_id)
        finally:
            cache.delete(schedule_key)

    timer = threading.Timer(delay, _retry)
    timer.daemon = True
    timer.start()


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


def _is_valid_provider_end_time(end_time: datetime | None, started_at: datetime | None) -> bool:
    if not end_time:
        return False
    # Ignore epoch placeholder values such as 1970-01-01 that some provider responses send for active calls.
    if end_time.year < 2000:
        return False
    if started_at and end_time < started_at:
        return False
    return True


def _has_provider_end_confirmation(call: CallSession, raw_payload: dict) -> bool:
    if not isinstance(raw_payload, dict):
        return False

    candidates: list[object] = []

    last_event = raw_payload.get("last_event")
    if isinstance(last_event, dict):
        candidates.append(_first_present(last_event, ("EndTime", "CompletedTime", "HangupTime")))
        if isinstance(last_event.get("Call"), dict):
            candidates.append(_first_present(last_event.get("Call", {}), ("EndTime", "CompletedTime", "HangupTime")))

    poll = raw_payload.get("exotel_poll")
    if isinstance(poll, dict):
        call_data = poll.get("call")
        raw_data = poll.get("raw")
        if isinstance(call_data, dict):
            candidates.append(_first_present(call_data, ("EndTime", "CompletedTime", "HangupTime")))
        if isinstance(raw_data, dict):
            candidates.append(_first_present(raw_data, ("EndTime", "CompletedTime", "HangupTime")))
            if isinstance(raw_data.get("Call"), dict):
                candidates.append(_first_present(raw_data.get("Call", {}), ("EndTime", "CompletedTime", "HangupTime")))

    started_at = call.answered_at or call.started_at or call.created_at
    for value in candidates:
        parsed = _parse_provider_datetime(value)
        if _is_valid_provider_end_time(parsed, started_at):
            return True
    return False


def _has_provider_answer_confirmation(call: CallSession, raw_payload: dict) -> bool:
    if not isinstance(raw_payload, dict):
        raw_payload = {}

    # Internal answer markers are the strongest signal.
    if call.answered_at:
        return True

    # Once we move into bridged/human states, treat the call as answered to
    # avoid showing pickup countdown while the SDR is already in-call.
    if call.status in {CallStatus.BRIDGED, CallStatus.HUMAN_DETECTED}:
        return True

    payload_disposition = _extract_provider_disposition(raw_payload)
    if payload_disposition == "answered":
        return True

    event_type = _extract_event_type(raw_payload)
    if event_type and any(token in event_type for token in ("answered", "connected")):
        return True

    candidates: list[object] = []
    last_event = raw_payload.get("last_event")
    if isinstance(last_event, dict):
        candidates.append(_first_present(last_event, ("AnsweredTime", "AnswerTime", "ConnectTime", "BridgeTime")))
        if isinstance(last_event.get("Call"), dict):
            candidates.append(
                _first_present(last_event.get("Call", {}), ("AnsweredTime", "AnswerTime", "ConnectTime", "BridgeTime"))
            )

    poll = raw_payload.get("exotel_poll")
    if isinstance(poll, dict):
        call_data = poll.get("call")
        raw_data = poll.get("raw")
        if isinstance(call_data, dict):
            candidates.append(_first_present(call_data, ("AnsweredTime", "AnswerTime", "ConnectTime", "BridgeTime")))
        if isinstance(raw_data, dict):
            candidates.append(_first_present(raw_data, ("AnsweredTime", "AnswerTime", "ConnectTime", "BridgeTime")))
            if isinstance(raw_data.get("Call"), dict):
                candidates.append(
                    _first_present(raw_data.get("Call", {}), ("AnsweredTime", "AnswerTime", "ConnectTime", "BridgeTime"))
                )

    started_at = call.started_at or call.created_at
    for value in candidates:
        parsed = _parse_provider_datetime(value)
        if _is_valid_provider_end_time(parsed, started_at):
            return True

    return False


def _is_call_waiting_for_customer_pickup(call: CallSession | None) -> bool:
    if not call:
        return False

    if call.ended_at:
        return False

    display_status = _derive_display_status(call)
    if display_status in {"answered", "completed", "sdr-cut"}:
        return False

    if call.status in {CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING}:
        return True

    if call.status in {CallStatus.BRIDGED, CallStatus.HUMAN_DETECTED}:
        raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
        return not _has_provider_answer_confirmation(call, raw_payload)

    return False


def _to_call_outcome(status: str) -> str:
    value = str(status or "").strip().lower()
    if value in {"answered", "completed"}:
        return "connected"
    if value in {"no-answer", "no_answer", "sdr-cut"}:
        return "no_answer"
    if value in {"busy"}:
        return "busy"
    if value in {"machine"}:
        return "machine"
    if value in {"failed", "cancelled", "canceled"}:
        return "bad_number"
    return ""


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


def _extract_webhook_metadata(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}

    sources: list[object] = [
        payload.get("CustomField"),
        payload.get("custom_field"),
        payload.get("customField"),
        payload.get("metadata"),
        payload.get("MetaData"),
        payload.get("UUI"),
        payload.get("user_data"),
    ]

    call_data = payload.get("Call")
    if isinstance(call_data, dict):
        sources.extend(
            [
                call_data.get("CustomField"),
                call_data.get("custom_field"),
                call_data.get("customField"),
                call_data.get("metadata"),
                call_data.get("MetaData"),
                call_data.get("UUI"),
                call_data.get("user_data"),
            ]
        )

    merged: dict[str, object] = {}
    for source in sources:
        parsed = _parse_json_like_dict(source)
        if parsed:
            merged.update(parsed)
    return merged


def _extract_call_public_id_from_payload(payload: dict) -> str:
    metadata = _extract_webhook_metadata(payload)
    candidates = [
        metadata.get("call_public_id"),
        metadata.get("call_id"),
        metadata.get("public_id"),
        payload.get("call_public_id") if isinstance(payload, dict) else None,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        try:
            parsed = UUID(value)
            return str(parsed)
        except (ValueError, TypeError):
            continue
    return ""


def _match_call_from_webhook_payload(payload: dict) -> tuple[CallSession | None, str]:
    public_id = _extract_call_public_id_from_payload(payload)
    if public_id:
        call = (
            CallSession.objects.select_related("agent")
            .filter(provider=ProviderType.EXOTEL, public_id=public_id)
            .first()
        )
        if call:
            return call, "custom_field_public_id"

    metadata = _extract_webhook_metadata(payload)
    campaign_id = _parse_positive_int(metadata.get("campaign_id"), 0)
    lead_id = _parse_positive_int(metadata.get("lead_id"), 0)
    if campaign_id and lead_id:
        call = (
            CallSession.objects.select_related("agent")
            .filter(provider=ProviderType.EXOTEL, campaign_id=campaign_id, lead_id=lead_id)
            .order_by("-created_at")
            .first()
        )
        if call:
            return call, "custom_field_campaign_lead"

    return None, ""


def _payload_contains_any(raw_payload: object, keywords: tuple[str, ...]) -> bool:
    tokens = _flatten_payload_text(raw_payload)
    if not tokens:
        return False
    return any(any(keyword in token for keyword in keywords) for token in tokens)


def _payload_has_terminal_signal(raw_payload: object) -> bool:
    return _payload_contains_any(
        raw_payload,
        (
            "completed",
            "terminal",
            "hangup",
            "disconnected",
            "failed",
            "busy",
            "no-answer",
            "no_answer",
            "cancelled",
            "canceled",
            "machine",
        ),
    )


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


def _is_duration_eligible_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"answered", "completed"}


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


def _campaign_name_from_lead(lead: Lead) -> str:
    metadata = lead.metadata if isinstance(lead.metadata, dict) else {}
    campaign = metadata.get("campaign_name")
    if campaign:
        return str(campaign)
    return "General"


def _build_call_logs_summary(rows: list[dict]) -> dict:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "").strip().lower().replace("_", "-")
        if not status:
            status = "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    answered = status_counts.get("answered", 0)
    failed = status_counts.get("failed", 0)
    no_answer = status_counts.get("no-answer", 0) + status_counts.get("no_answer", 0)

    return {
        "total_calls": len(rows),
        "answered_calls": answered,
        "failed_calls": failed,
        "no_answer_calls": no_answer,
        "busy_calls": status_counts.get("busy", 0),
        "cancelled_calls": status_counts.get("cancelled", 0) + status_counts.get("canceled", 0),
        "completed_calls": status_counts.get("completed", 0),
        "initiated_calls": status_counts.get("initiated", 0),
        "status_counts": status_counts,
    }


def _serialize_call_log(call: CallSession, include_raw: bool = False) -> dict:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    hubspot_sync = raw_payload.get("hubspot_sync") if isinstance(raw_payload.get("hubspot_sync"), dict) else {}
    transcript_status = str(raw_payload.get("transcript_status") or "").strip().lower()
    transcript = str(raw_payload.get("transcript") or "").strip()
    transcript_error = str(raw_payload.get("transcript_error") or "").strip()
    disposition = _safe_get_call_disposition(call)

    if call.transcript_url:
        transcript_status = "completed"
    elif transcript_status not in {"processing", "completed", "failed"}:
        transcript_status = "failed" if transcript_error else "none"

    initiated_at = call.started_at or call.created_at
    init_request = raw_payload.get("init_request") if isinstance(raw_payload.get("init_request"), dict) else {}
    campaign_name = _campaign_name_from_lead(call.lead)
    if init_request.get("campaign_name"):
        campaign_name = str(init_request.get("campaign_name"))

    result = {
        "id": call.id,
        "public_id": str(call.public_id),
        "campaign_id": call.campaign_id,
        "contact_name": call.lead.full_name,
        "contact_phone": call.lead.phone_e164,
        "campaign_name": campaign_name,
        "agent_name": call.agent.display_name if call.agent else "Unassigned",
        "status": _derive_display_status(call),
        "internal_status": call.status,
        "duration_formatted": _format_duration(call),
        "recording_url": call.recording_url,
        "transcript_status": transcript_status,
        "transcript": transcript,
        "transcript_error": transcript_error,
        "initiated_at": initiated_at.isoformat() if initiated_at else None,
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "answered_at": call.answered_at.isoformat() if call.answered_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "provider_call_uuid": call.provider_call_uuid,
        "payload_event_type": _extract_event_type(raw_payload),
        "payload_disposition": _extract_provider_disposition(raw_payload),
        "terminal_processed": bool(raw_payload.get("campaign_terminal_processed")),
        "call_outcome": disposition.outcome if disposition else "",
        "agent_notes": disposition.notes if disposition else "",
        "deal_id": disposition.hubspot_deal_id if disposition else "",
        "deal_name": disposition.hubspot_deal_name if disposition else "",
        "hubspot_sync_status": str(hubspot_sync.get("last_status") or ""),
        "hubspot_synced_at": str(hubspot_sync.get("last_synced_at") or ""),
        "hubspot_call_object_id": str(hubspot_sync.get("call_object_id") or ""),
        "hubspot_task_object_id": str(hubspot_sync.get("task_object_id") or ""),
        "hubspot_sync_error": str(hubspot_sync.get("last_error") or ""),
    }
    if include_raw:
        result["raw_provider_payload"] = raw_payload
    return result


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def _map_exotel_status_to_call_status(status_text: str) -> str:
    value = str(status_text or "").strip().lower()
    if not value:
        return ""

    if any(token in value for token in ("busy", "failed", "error", "rejected", "no-answer", "no_answer", "cancel")):
        return CallStatus.FAILED
    if any(token in value for token in ("completed", "terminal", "hangup", "disconnected")):
        return CallStatus.COMPLETED
    if any(token in value for token in ("answered", "connected", "in-progress", "inprogress")):
        return CallStatus.BRIDGED
    if "ring" in value:
        return CallStatus.RINGING
    if any(token in value for token in ("queued", "initiated", "start", "dialing", "progress")):
        return CallStatus.DIALING
    return ""


def _is_terminal_provider_status(status_text: str) -> bool:
    value = str(status_text or "").strip().lower()
    if not value:
        return False
    return any(
        token in value
        for token in (
            "completed",
            "terminal",
            "hangup",
            "disconnected",
            "failed",
            "busy",
            "no-answer",
            "no_answer",
            "cancelled",
            "canceled",
            "machine",
        )
    )


def _apply_exotel_snapshot(call: CallSession, call_data: dict, raw_response: dict) -> bool:
    if not isinstance(call_data, dict):
        call_data = {}
    if not isinstance(raw_response, dict):
        raw_response = {}

    update_fields: list[str] = []

    provider_sid = str(
        _first_present(call_data, ("Sid", "CallSid", "UUID", "CallUUID", "id"))
        or _first_present(raw_response.get("Call", {}), ("Sid", "CallSid", "UUID", "CallUUID", "id"))
        or _first_present(raw_response, ("Sid", "CallSid", "UUID", "CallUUID", "id"))
        or ""
    ).strip()
    if provider_sid and call.provider_call_uuid != provider_sid:
        call.provider_call_uuid = provider_sid
        update_fields.append("provider_call_uuid")

    status_value = _first_present(call_data, ("Status", "CallStatus", "EventType", "State"))
    if status_value in (None, ""):
        status_value = _first_present(raw_response.get("Call", {}), ("Status", "CallStatus", "EventType", "State"))
    if status_value in (None, ""):
        status_value = _first_present(raw_response, ("Status", "CallStatus", "EventType", "State"))
    status_text = str(status_value or "")
    mapped_status = _map_exotel_status_to_call_status(status_text)
    terminal_signal = _is_terminal_provider_status(status_text)
    failed_signal = any(
        token in status_text.lower()
        for token in ("busy", "no-answer", "no_answer", "cancelled", "canceled", "failed", "error", "rejected")
    )

    if terminal_signal and mapped_status in {"", CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING, CallStatus.BRIDGED, CallStatus.HUMAN_DETECTED}:
        mapped_status = CallStatus.FAILED if failed_signal else CallStatus.COMPLETED

    amd_value = _first_present(call_data, ("AnsweredBy", "Machine", "AmdStatus"))
    amd = _normalize_amd(str(amd_value)) if amd_value is not None else None

    next_status = mapped_status or call.status
    if amd == "machine":
        next_status = CallStatus.MACHINE_DETECTED
    elif amd == "human" and next_status in {CallStatus.DIALING, CallStatus.RINGING, CallStatus.QUEUED}:
        next_status = CallStatus.HUMAN_DETECTED

    if next_status and call.status != next_status:
        call.status = next_status
        update_fields.append("status")

    started_at = _parse_provider_datetime(
        _first_present(
            call_data,
            (
                "StartTime",
                "StartDate",
                "DateCreated",
                "Created",
                "CreatedAt",
            ),
        )
    )
    if started_at and (not call.started_at or started_at < call.started_at):
        call.started_at = started_at
        update_fields.append("started_at")

    answered_at = _parse_provider_datetime(
        _first_present(call_data, ("AnsweredTime", "AnswerTime", "ConnectTime", "BridgeTime"))
    )
    if answered_at and (not call.answered_at or answered_at < call.answered_at):
        call.answered_at = answered_at
        update_fields.append("answered_at")

    ended_at = _parse_provider_datetime(
        _first_present(call_data, ("EndTime", "CompletedTime", "HangupTime"))
    )
    started_reference = call.answered_at or call.started_at or call.created_at
    can_trust_provider_end = bool(terminal_signal or mapped_status in {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.MACHINE_DETECTED})
    if (
        ended_at
        and can_trust_provider_end
        and _is_valid_provider_end_time(ended_at, started_reference)
        and (not call.ended_at or ended_at > call.ended_at)
    ):
        call.ended_at = ended_at
        update_fields.append("ended_at")
    elif terminal_signal or mapped_status in {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.MACHINE_DETECTED}:
        # Never fabricate end-time for successful calls.
        # Only failed/machine outcomes are allowed to auto-close without explicit provider EndTime.
        if not call.ended_at:
            if failed_signal or mapped_status in {CallStatus.FAILED, CallStatus.MACHINE_DETECTED}:
                call.ended_at = timezone.now()
                update_fields.append("ended_at")

    payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    recording_url = _extract_recording_url(call_data, raw_response) or _normalize_recording_url(call.recording_url)

    should_try_recording_fetch = bool(
        not recording_url
        and call.provider_call_uuid
        and (call.ended_at or terminal_signal or mapped_status in {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.MACHINE_DETECTED})
    )
    if should_try_recording_fetch:
        lookup = payload.get("exotel_recording_lookup") if isinstance(payload.get("exotel_recording_lookup"), dict) else {}
        attempt_count = max(0, int(lookup.get("attempts") or 0))
        last_attempt_at = _parse_provider_datetime(lookup.get("at"))
        recently_attempted = bool(last_attempt_at and (timezone.now() - last_attempt_at).total_seconds() < 30)
        terminal_not_found = str(lookup.get("status") or "").strip().lower() == "not_found" and attempt_count >= 5
        if not recently_attempted and not terminal_not_found:
            provider = get_provider()
            if isinstance(provider, ExotelProvider):
                recording_fetch = provider.fetch_call_recording(call.provider_call_uuid)
                attempt_count += 1
                lookup_payload = {
                    "at": timezone.now().isoformat(),
                    "attempts": attempt_count,
                    "status": "not_found",
                }
                if recording_fetch.get("ok") and recording_fetch.get("recording_url"):
                    recording_url = _normalize_recording_url(recording_fetch.get("recording_url"))
                    lookup_payload["status"] = "found"
                    lookup_payload["endpoint"] = str(recording_fetch.get("endpoint") or "")
                else:
                    lookup_payload["error"] = str(recording_fetch.get("error") or "")
                    endpoint = recording_fetch.get("endpoint")
                    if endpoint:
                        lookup_payload["endpoint"] = str(endpoint)
                payload["exotel_recording_lookup"] = lookup_payload

    if recording_url and call.recording_url != recording_url:
        call.recording_url = recording_url
        update_fields.append("recording_url")

    payload["exotel_poll"] = {
        "fetched_at": timezone.now().isoformat(),
        "call": call_data,
        "raw": raw_response,
    }
    call.raw_provider_payload = payload
    update_fields.append("raw_provider_payload")

    if not update_fields:
        return False

    call.save(update_fields=list(dict.fromkeys(update_fields)))
    if call.recording_url:
        _maybe_schedule_call_recording_transcription(call, reason="exotel_snapshot")
    return True


def _extract_recording_url(call_data: dict, raw_response: dict) -> str:
    keys = (
        "RecordingUrl",
        "RecordingURL",
        "RecordingUrlMp3",
        "RecordingUrlWav",
        "CallRecordingUrl",
        "RecordingFileUrl",
        "recording_url",
    )

    for source in (
        call_data,
        raw_response.get("Call") if isinstance(raw_response, dict) else None,
        raw_response,
    ):
        if not isinstance(source, dict):
            continue
        value = _first_present(source, keys)
        if value:
            normalized = _normalize_recording_url(value)
            if normalized:
                return normalized

    fallback = _scan_for_recording_url(raw_response)
    return _normalize_recording_url(fallback) if fallback else ""


def _scan_for_recording_url(obj: object) -> str:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key).lower()
            if isinstance(value, str):
                text = value.strip()
                if "record" in key_text or any(ext in text.lower() for ext in (".mp3", ".wav")) or "/record" in text.lower():
                    normalized = _normalize_recording_url(text)
                    if normalized:
                        return normalized
            result = _scan_for_recording_url(value)
            if result:
                return result
        return ""

    if isinstance(obj, list):
        for item in obj:
            result = _scan_for_recording_url(item)
            if result:
                return result
        return ""

    return ""


def _normalize_recording_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return f"https:{text}"

    exotel_subdomain = os.getenv("EXOTEL_SUBDOMAIN", "").replace("@", "").strip()
    if not exotel_subdomain:
        return ""

    if text.startswith("/"):
        return f"https://{exotel_subdomain}{text}"
    if text.startswith("v1/"):
        return f"https://{exotel_subdomain}/{text}"
    if text.startswith(exotel_subdomain):
        return f"https://{text}"
    return ""


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
