import mimetypes
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import requests
from django.core.cache import cache
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import (
    CallSession,
    CallStatus,
    ProviderType,
    RecordingAsset,
    RecordingSource,
    TranscriptStatus,
)
from ..services.call_utils import (
    _duration_seconds_for_call,
    _parse_bool,
)
from ._helpers import (
    AUTO_TRANSCRIBE_DOWNLOAD_RETRIES,
    AUTO_TRANSCRIBE_DOWNLOAD_RETRY_DELAY_SECONDS,
    AUTO_TRANSCRIBE_RECORDINGS,
    AUTO_TRANSCRIBE_RETRY_FAILED_SECONDS,
    AUTO_TRANSCRIBE_STALE_PROCESSING_SECONDS,
    OPENAI_AUDIO_TRANSCRIPT_ENDPOINT,
    RECORDING_UPLOAD_ALLOWED_EXTENSIONS,
    RECORDING_UPLOAD_MAX_BYTES,
    TRANSCRIPTION_BACKEND,
    TRANSCRIPTION_ENGLISH_ONLY,
    TRANSCRIPTION_NON_ENGLISH_ERROR,
    TRANSCRIPTION_PROGRESS_CACHE_PREFIX,
    TRANSCRIPTION_PROGRESS_TTL_SECONDS,
    WHISPER_BEAM_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_CONDITION_ON_PREVIOUS_TEXT,
    WHISPER_DEVICE,
    WHISPER_LANGUAGE,
    WHISPER_MODEL_NAME,
    WHISPER_TEMPERATURE,
    WHISPER_VAD_FILTER,
    _build_absolute_media_url,
    _format_seconds,
    _load_json_body,
    _parse_positive_int,
    logger,
)

# ─── module-level state ──────────────────────────────────────────────
_WHISPER_MODEL_INSTANCE = None
_WHISPER_MODEL_LOCK = threading.Lock()


# ─── transcript segment normalization ────────────────────────────────
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


# ─── transcription language helpers ──────────────────────────────────
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


# ─── transcription progress cache ───────────────────────────────────
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


# ─── recording audio helpers ────────────────────────────────────────
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


# ─── call transcript payload helpers ────────────────────────────────
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
            # Function-level import to avoid circular dependency with campaign_views
            from .campaign_views import _sync_exotel_call_details as _sync_exotel
            _sync_exotel(calls_for_sync, max_fetch=sync_limit)

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


# ─── audio download helpers ─────────────────────────────────────────
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


# ─── audio duration helpers ──────────────────────────────────────────
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


# ─── whisper model helpers ───────────────────────────────────────────
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


# ─── transcript save / mark failed ──────────────────────────────────
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


# ─── core transcription runner ───────────────────────────────────────
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


# ─── transcription state helpers ─────────────────────────────────────
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

    recording_id = int(recording.id)

    from ..tasks import transcribe_recording_task
    transcribe_recording_task.delay(recording_id, force=force, language=language, reason=reason)
    return True


def _maybe_schedule_call_recording_transcription(call: CallSession, reason: str = "") -> bool:
    if not call or not str(call.recording_url or "").strip():
        return False
    recording, _ = _upsert_recording_asset_from_call(call)
    if not recording:
        return False
    return _schedule_recording_auto_transcription(recording, reason=reason)


# ─── Exotel call sync (standalone, for call_views import) ────────────
def _sync_exotel_call_details(calls: list[CallSession], max_fetch: int = 20) -> dict:
    # Function-level import to avoid circular dependency with campaign_views
    from .campaign_views import _poll_single_exotel_call
    from ..services.hubspot_service import _sync_call_to_hubspot

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
                from .campaign_views import _handle_campaign_call_terminal
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


# ─── view functions ─────────────────────────────────────────────────
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
