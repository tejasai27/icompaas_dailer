from uuid import UUID

from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.telephony.exotel import ExotelProvider
from apps.telephony.factory import get_provider

from ..models import (
    CallDisposition,
    CallOutcome,
    CallSession,
    CallStatus,
    Lead,
    ProviderType,
    RecordingSource,
    TranscriptStatus,
)
from ..services.call_utils import (
    _derive_display_status,
    _duration_seconds_for_call,
    _extract_event_type,
    _extract_provider_disposition,
    _parse_bool,
)
from ..services.hubspot_service import (
    _call_disposition_deal_fields_available,
    _call_session_select_related_fields,
    _normalize_hubspot_deal_id,
    _safe_get_call_disposition,
    _sync_call_to_hubspot,
)
from ._helpers import (
    _format_duration,
    _load_json_body,
    _parse_positive_int,
    logger,
)
from .recording_views import (
    _maybe_schedule_call_recording_transcription,
    _serialize_recording_asset,
    _sync_exotel_call_details,
    _upsert_recording_asset_from_call,
    _is_terminal_call_for_transcription,
    _schedule_recording_auto_transcription,
)


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

    try:
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
    except (ProgrammingError, OperationalError) as exc:
        logger.exception("list_call_logs_failed: %s", exc)
        empty_summary = _build_call_logs_summary([])
        return JsonResponse(
            {
                "count": 0,
                "page": page,
                "page_size": page_size,
                "results": [],
                "summary": empty_summary,
                "summary_all": empty_summary,
                "warning": "call log data unavailable",
            }
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
        # Function-level import to avoid circular dependency with campaign_views
        from .campaign_views import _poll_single_exotel_call
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
