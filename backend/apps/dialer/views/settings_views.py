import re
from uuid import UUID, uuid4

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import (
    CallSession,
    CRMSyncLog,
    HubSpotDealAssociationMode,
)
from ..services.call_utils import _parse_bool
from ..services.hubspot_service import (
    _call_session_select_related_fields,
    _get_hubspot_settings,
    _hubspot_api_request,
    _normalize_hubspot_deal_id,
    _resolve_hubspot_access_token,
    _serialize_hubspot_record,
    _serialize_hubspot_settings,
    _sync_call_to_hubspot,
)
from ._helpers import (
    RUNTIME_EXOTEL_WAIT_AUDIO_CACHE_KEY,
    WAIT_AUDIO_ALLOWED_EXTENSIONS,
    WAIT_AUDIO_MAX_BYTES,
    _build_absolute_media_url,
    _get_runtime_exotel_wait_audio,
    _load_json_body,
    _parse_positive_int,
)
from .call_views import _serialize_call_log


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
