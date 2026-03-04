import csv
import io
import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.telephony.base import DialRequest
from apps.telephony.exotel import ExotelProvider
from apps.telephony.factory import get_provider

from .models import AgentProfile, AgentStatus, CallSession, CallStatus, Lead, LeadDialState, ProviderType


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


@require_GET
def list_agents(request: HttpRequest) -> JsonResponse:
    agents = AgentProfile.objects.select_related("user").order_by("id")
    return JsonResponse(
        {
            "agents": [
                {
                    "id": agent.id,
                    "display_name": agent.display_name,
                    "status": agent.status,
                    "user_id": agent.user_id,
                }
                for agent in agents
            ]
        }
    )


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

    queryset = Lead.objects.select_related("dial_state").order_by("-id")
    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search)
            | Q(phone_e164__icontains=search)
            | Q(company_name__icontains=search)
            | Q(email__icontains=search)
        )

    count = queryset.count()
    offset = (page - 1) * page_size
    leads = list(queryset[offset : offset + page_size])

    results = []
    for lead in leads:
        dial_state = getattr(lead, "dial_state", None)
        status = dial_state.last_outcome if dial_state and dial_state.last_outcome else "pending"
        retry_count = dial_state.attempt_count if dial_state else 0
        last_called_at = dial_state.last_attempt_at.isoformat() if dial_state and dial_state.last_attempt_at else None

        results.append(
            {
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
            }
        )

    return JsonResponse({"count": count, "page": page, "page_size": page_size, "results": results})


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
        company_name = _pick_value(row, ["company_name", "company", "Company", "organization"]) or ""
        owner_hint = _pick_value(row, ["owner_hint", "owner", "agent", "sdr", "Owner"]) or ""
        timezone_value = _pick_value(row, ["timezone", "tz", "Timezone"]) or "Asia/Kolkata"
        external_id = _pick_value(row, ["external_id", "id", "lead_id", "Lead ID"]) or ""

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
                "metadata": {"raw_csv": row, "campaign_name": campaign_name},
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

    return JsonResponse(
        {
            "ok": True,
            "file_name": upload.name,
            "campaign_name": campaign_name,
            "total_rows": len(parsed_rows) + len(invalid_rows) + duplicate_in_file_count,
            "created_count": created_count,
            "duplicate_existing_count": duplicate_existing_count,
            "duplicate_in_file_count": duplicate_in_file_count,
            "invalid_count": len(invalid_rows),
            "invalid_rows": invalid_rows[:20],
        },
        status=201,
    )


@csrf_exempt
@require_POST
def create_manual_leads(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    campaign_name = str(payload.get("campaign_name") or "").strip()
    timezone_default = str(payload.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata"
    source_name = campaign_name or "manual-entry"

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
        company_name = _pick_value(row, ["company_name", "company", "Company", "organization"]) or ""
        owner_hint = _pick_value(row, ["owner_hint", "owner", "agent", "sdr", "Owner"]) or ""
        timezone_value = _pick_value(row, ["timezone", "tz", "Timezone"]) or timezone_default
        external_id = _pick_value(row, ["external_id", "id", "lead_id", "Lead ID"]) or ""

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
                "metadata": {"raw_manual": row, "campaign_name": campaign_name},
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

    return JsonResponse(
        {
            "ok": True,
            "campaign_name": campaign_name,
            "total_rows": len(parsed_rows) + len(invalid_rows) + duplicate_in_payload_count,
            "created_count": created_count,
            "duplicate_existing_count": duplicate_existing_count,
            "duplicate_in_payload_count": duplicate_in_payload_count,
            "invalid_count": len(invalid_rows),
            "invalid_rows": invalid_rows[:20],
        },
        status=201,
    )


@require_GET
def list_call_logs(request: HttpRequest) -> JsonResponse:
    page = _parse_positive_int(request.GET.get("page"), 1)
    page_size = 20
    search = str(request.GET.get("search") or "").strip()
    status_filter = str(request.GET.get("status") or "").strip().lower().replace("_", "-")
    ordering = str(request.GET.get("ordering") or "-initiated_at").strip()

    queryset = CallSession.objects.select_related("lead", "agent")

    if search:
        queryset = queryset.filter(
            Q(lead__full_name__icontains=search)
            | Q(lead__phone_e164__icontains=search)
            | Q(lead__company_name__icontains=search)
            | Q(agent__display_name__icontains=search)
            | Q(provider_call_uuid__icontains=search)
        )

    # Frontend sends "initiated_at"; map to model fields.
    if ordering in {"initiated_at", "created_at"}:
        queryset = queryset.order_by("started_at", "created_at")
    elif ordering in {"-initiated_at", "-created_at"}:
        queryset = queryset.order_by("-started_at", "-created_at")
    else:
        queryset = queryset.order_by("-created_at")

    all_calls = list(queryset)
    results = [_serialize_call_log(call) for call in all_calls]
    summary_all = _build_call_logs_summary(results)

    if status_filter:
        results = [
            row
            for row in results
            if str(row.get("status", "")).strip().lower().replace("_", "-") == status_filter
        ]
    summary_filtered = _build_call_logs_summary(results)

    count = len(results)
    offset = (page - 1) * page_size
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


@csrf_exempt
@require_POST
def sync_exotel_call_logs(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    limit = min(_parse_positive_int(payload.get("limit"), 50), 200)
    only_open = _parse_bool(payload.get("only_open"), True)

    provider = get_provider()
    if not isinstance(provider, ExotelProvider):
        return JsonResponse({"error": "TELEPHONY_PROVIDER must be set to exotel"}, status=400)
    if not provider.configured:
        return JsonResponse({"error": "exotel_not_configured"}, status=400)

    queryset = CallSession.objects.select_related("lead", "agent").filter(
        provider=ProviderType.EXOTEL
    ).exclude(provider_call_uuid="")
    if only_open:
        queryset = queryset.filter(ended_at__isnull=True)

    calls = list(queryset.order_by("-created_at")[:limit])
    synced = 0
    updated = 0
    failed: list[dict] = []

    for call in calls:
        result = provider.fetch_call(call.provider_call_uuid)
        if not result.get("ok"):
            failed.append(
                {
                    "call_id": call.id,
                    "provider_call_uuid": call.provider_call_uuid,
                    "error": result.get("error", "unknown_error"),
                }
            )
            continue

        changed = _apply_exotel_snapshot(call, result.get("call") or {}, result.get("raw") or {})
        synced += 1
        if changed:
            updated += 1

    return JsonResponse(
        {
            "ok": True,
            "processed": len(calls),
            "synced": synced,
            "updated": updated,
            "failed_count": len(failed),
            "failed": failed[:25],
        }
    )


@csrf_exempt
@require_POST
def trigger_transcription(request: HttpRequest, call_id: int) -> JsonResponse:
    call = get_object_or_404(CallSession, id=call_id)
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    raw_payload["transcript_status"] = "processing"
    call.raw_provider_payload = raw_payload
    call.save(update_fields=["raw_provider_payload"])
    return JsonResponse({"ok": True, "call_id": call.id, "transcript_status": "processing"})


@csrf_exempt
@require_POST
def start_exotel_call(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)

    lead_id = payload.get("lead_id")
    agent_id = payload.get("agent_id")
    agent_phone = payload.get("agent_phone")

    if not lead_id or not agent_id or not agent_phone:
        return JsonResponse(
            {"error": "lead_id, agent_id and agent_phone are required"},
            status=400,
        )

    lead = get_object_or_404(Lead, id=lead_id)
    agent = get_object_or_404(AgentProfile, id=agent_id)

    provider = get_provider()
    if not isinstance(provider, ExotelProvider):
        return JsonResponse(
            {"error": "TELEPHONY_PROVIDER must be set to exotel for this endpoint"},
            status=400,
        )

    callback_url = str(payload.get("status_callback_url") or "").strip()

    max_call_duration_seconds = _parse_positive_int(
        payload.get("max_duration_seconds"),
        int(getattr(settings, "EXOTEL_MAX_CALL_DURATION_SECONDS", 60) or 60),
    )
    if not callback_url:
        public_base = str(getattr(settings, "PUBLIC_WEBHOOK_BASE_URL", "") or "").strip().rstrip("/")
        if public_base:
            callback_url = f"{public_base}/api/v1/dialer/webhooks/exotel/"

    call = CallSession.objects.create(
        lead=lead,
        agent=agent,
        provider=ProviderType.EXOTEL,
        status=CallStatus.DIALING,
        started_at=timezone.now(),
        raw_provider_payload={
            "init_request": {
                "lead_id": lead.id,
                "agent_id": agent.id,
                "agent_phone": agent_phone,
                "lead_phone": lead.phone_e164,
                "dial_sequence": "lead_first",
                "max_duration_seconds": max_call_duration_seconds,
            }
        },
    )

    dial_request = DialRequest(
        lead_id=lead.id,
        # Dial lead first, then bridge to agent.
        from_number=lead.phone_e164,
        to_number=agent_phone,
        callback_url=callback_url,
        caller_id=str(payload.get("caller_id") or os.getenv("EXOTEL_CALLER_ID", "")).strip() or None,
        metadata={"call_public_id": str(call.public_id), "lead_id": lead.id, "agent_id": agent.id},
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
        return JsonResponse({"error": "exotel_call_failed", "details": dial_response.raw}, status=502)

    call.provider_call_uuid = dial_response.provider_call_id
    call.raw_provider_payload = {
        "init_request": call.raw_provider_payload.get("init_request", {}),
        "init_response": dial_response.raw,
    }
    call.save(update_fields=["provider_call_uuid", "raw_provider_payload"])

    agent.status = AgentStatus.BUSY
    agent.save(update_fields=["status", "last_state_change"])

    return JsonResponse(
        {
            "call": {
                "id": str(call.public_id),
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
    provider = ExotelProvider()
    event = provider.parse_webhook(payload)

    if not event.provider_call_id:
        return JsonResponse({"ok": False, "error": "missing provider call id"}, status=400)

    call = (
        CallSession.objects.select_related("agent")
        .filter(provider=ProviderType.EXOTEL, provider_call_uuid=event.provider_call_id)
        .first()
    )
    if not call:
        return JsonResponse({"ok": True, "ignored": "unknown_call"})

    now = timezone.now()
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    events = raw_payload.get("events", [])
    if not isinstance(events, list):
        events = []
    events.append(payload)
    raw_payload["events"] = events[-50:]
    raw_payload["last_event"] = payload
    call.raw_provider_payload = raw_payload

    update_fields = ["raw_provider_payload"]
    event_type = event.event_type.lower()
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

    if any(token in event_type for token in ("answered", "connected", "in-progress", "inprogress")):
        call.status = CallStatus.BRIDGED
        call.answered_at = call.answered_at or now
        update_fields.extend(["status", "answered_at"])

    if any(
        token in event_type
        for token in (
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
    ):
        if amd != "machine":
            call.status = CallStatus.FAILED if "failed" in event_type else CallStatus.COMPLETED
        call.ended_at = now
        call.wrap_up_deadline = now + timedelta(seconds=15)
        update_fields.extend(["status", "ended_at", "wrap_up_deadline"])

        if call.agent:
            call.agent.status = AgentStatus.WRAP_UP
            call.agent.save(update_fields=["status", "last_state_change"])

    call.save(update_fields=list(dict.fromkeys(update_fields)))

    return JsonResponse({"ok": True, "call_id": str(call.public_id), "status": call.status, "amd": amd})


def _pick_value(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


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

    payload_disposition = _extract_provider_disposition(raw_payload)
    if payload_disposition:
        return payload_disposition

    event_type = _extract_event_type(raw_payload)

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


def _format_duration(call: CallSession) -> str:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    duration_seconds = _extract_duration_seconds(raw_payload)
    if duration_seconds is not None and duration_seconds >= 0:
        return _format_seconds(duration_seconds)

    start_at = call.answered_at
    end_at = call.ended_at
    if not start_at or not end_at:
        # Fallback when provider didn't send duration but we have terminal timestamps.
        start_at = call.started_at or call.created_at
        if not start_at or not end_at:
            return "-"

    total_seconds = max(0, int((end_at - start_at).total_seconds()))
    return _format_seconds(total_seconds)


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


def _extract_duration_seconds(raw_payload: dict) -> int | None:
    preferred_keys = (
        "CallDuration",
        "DialCallDuration",
        "ConversationDuration",
        "Duration",
        "duration",
        "BillSec",
        "billsec",
        "TalkTime",
        "talk_time",
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
                if "duration" in key_text or "billsec" in key_text or "talk" in key_text:
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


def _serialize_call_log(call: CallSession) -> dict:
    raw_payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
    transcript_status = str(raw_payload.get("transcript_status") or "").strip().lower()
    transcript = str(raw_payload.get("transcript") or "").strip()

    if call.transcript_url:
        transcript_status = "completed"
    elif transcript_status not in {"processing", "completed"}:
        transcript_status = "none"

    initiated_at = call.started_at or call.created_at
    init_request = raw_payload.get("init_request") if isinstance(raw_payload.get("init_request"), dict) else {}
    campaign_name = _campaign_name_from_lead(call.lead)
    if init_request.get("campaign_name"):
        campaign_name = str(init_request.get("campaign_name"))

    return {
        "id": call.id,
        "public_id": str(call.public_id),
        "contact_name": call.lead.full_name,
        "contact_phone": call.lead.phone_e164,
        "campaign_name": campaign_name,
        "agent_name": call.agent.display_name if call.agent else "Unassigned",
        "status": _derive_display_status(call),
        "duration_formatted": _format_duration(call),
        "recording_url": call.recording_url,
        "transcript_status": transcript_status,
        "transcript": transcript,
        "initiated_at": initiated_at.isoformat() if initiated_at else None,
        "provider_call_uuid": call.provider_call_uuid,
    }


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


def _apply_exotel_snapshot(call: CallSession, call_data: dict, raw_response: dict) -> bool:
    if not isinstance(call_data, dict):
        call_data = {}
    if not isinstance(raw_response, dict):
        raw_response = {}

    update_fields: list[str] = []

    provider_sid = str(
        _first_present(call_data, ("Sid", "CallSid", "UUID", "CallUUID", "id")) or ""
    ).strip()
    if provider_sid and call.provider_call_uuid != provider_sid:
        call.provider_call_uuid = provider_sid
        update_fields.append("provider_call_uuid")

    status_value = _first_present(call_data, ("Status", "CallStatus", "EventType", "State"))
    mapped_status = _map_exotel_status_to_call_status(str(status_value or ""))
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
        _first_present(call_data, ("EndTime", "CompletedTime", "HangupTime", "DateUpdated", "UpdatedAt"))
    )
    if ended_at and (not call.ended_at or ended_at > call.ended_at):
        call.ended_at = ended_at
        update_fields.append("ended_at")

    if call.status in {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.MACHINE_DETECTED} and not call.ended_at:
        call.ended_at = timezone.now()
        update_fields.append("ended_at")

    recording_url = str(
        _first_present(
            call_data,
            (
                "RecordingUrl",
                "RecordingURL",
                "RecordingUrlMp3",
                "RecordingUrlWav",
                "CallRecordingUrl",
            ),
        )
        or ""
    ).strip()
    if recording_url and call.recording_url != recording_url:
        call.recording_url = recording_url
        update_fields.append("recording_url")

    payload = call.raw_provider_payload if isinstance(call.raw_provider_payload, dict) else {}
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
    return True


def _parse_positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


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
