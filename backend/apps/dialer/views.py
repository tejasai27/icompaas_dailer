import csv
import io
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
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
    CallSession,
    CallStatus,
    Lead,
    LeadDialState,
    ProviderType,
)

logger = logging.getLogger("dialer.campaign")


def _debug_runtime(tag: str, payload: object) -> None:
    try:
        text = json.dumps(payload, default=str)
    except Exception:
        text = str(payload)
    print(f"[EXOTEL_DEBUG] {tag}: {text}", flush=True)
    logger.info("EXOTEL_DEBUG %s %s", tag, text)


def _active_call_not_ended_filter() -> Q:
    # Exotel can sometimes send epoch placeholder end-times for active calls.
    # Treat those rows as not-ended to avoid accidental parallel dispatch.
    cutoff = timezone.make_aware(datetime(2000, 1, 1), timezone.get_current_timezone())
    return Q(ended_at__isnull=True) | Q(ended_at__lt=cutoff)


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


@require_GET
def campaign_timeline(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)
    limit = max(1, min(_parse_positive_int(request.GET.get("limit"), 200), 1000))
    events = _get_campaign_timeline(campaign, limit=limit)
    return JsonResponse({"campaign_id": campaign.id, "count": len(events), "results": events})


@csrf_exempt
@require_POST
def clear_campaign_timeline(request: HttpRequest, campaign_id: int) -> JsonResponse:
    campaign = get_object_or_404(Campaign, id=campaign_id)

    cleared = 0
    with transaction.atomic():
        locked_campaign = (
            Campaign.objects.select_for_update()
            .only("id", "metadata", "updated_at")
            .filter(id=campaign.id)
            .first()
        )
        if not locked_campaign:
            return JsonResponse({"error": "campaign_not_found"}, status=404)

        metadata = locked_campaign.metadata if isinstance(locked_campaign.metadata, dict) else {}
        timeline = metadata.get("timeline")
        if isinstance(timeline, list):
            cleared = len(timeline)
        metadata.pop("timeline", None)
        locked_campaign.metadata = metadata
        locked_campaign.save(update_fields=["metadata", "updated_at"])

    logger.info("campaign_timeline_cleared campaign_id=%s cleared=%s", campaign.id, cleared)
    return JsonResponse({"ok": True, "campaign_id": campaign.id, "cleared": cleared})


@csrf_exempt
@require_POST
def clear_all_campaign_timelines(request: HttpRequest) -> JsonResponse:
    campaigns = list(Campaign.objects.only("id", "metadata", "updated_at").order_by("id"))
    cleared_campaigns = 0
    cleared_events = 0

    with transaction.atomic():
        for campaign in campaigns:
            metadata = campaign.metadata if isinstance(campaign.metadata, dict) else {}
            timeline = metadata.get("timeline")
            if not isinstance(timeline, list):
                continue
            cleared_events += len(timeline)
            metadata.pop("timeline", None)
            campaign.metadata = metadata
            campaign.save(update_fields=["metadata", "updated_at"])
            cleared_campaigns += 1

    logger.info(
        "campaign_timeline_cleared_all cleared_campaigns=%s cleared_events=%s",
        cleared_campaigns,
        cleared_events,
    )
    return JsonResponse(
        {
            "ok": True,
            "cleared_campaigns": cleared_campaigns,
            "cleared_events": cleared_events,
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

    results = []
    for lead in leads:
        dial_state = getattr(lead, "dial_state", None)
        status = dial_state.last_outcome if dial_state and dial_state.last_outcome else "pending"
        retry_count = dial_state.attempt_count if dial_state else 0
        last_called_at = dial_state.last_attempt_at.isoformat() if dial_state and dial_state.last_attempt_at else None
        metadata = lead.metadata if isinstance(lead.metadata, dict) else {}
        campaign_settings = metadata.get("campaign_settings")
        if not isinstance(campaign_settings, dict):
            campaign_settings = {}

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
                "campaign_name": str(metadata.get("campaign_name") or ""),
                "campaign_settings": campaign_settings,
            }
        )

    return JsonResponse({"count": count, "page": page, "page_size": page_size, "results": results})


@require_GET
def list_contacts(request: HttpRequest) -> JsonResponse:
    # Alias kept for frontend pages that still use /contacts/.
    return list_leads(request)


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

    queryset = CallSession.objects.select_related("lead", "agent")

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

    if any(token in normalized_event for token in ("answered", "connected", "in-progress", "inprogress")):
        call.status = CallStatus.BRIDGED
        call.answered_at = call.answered_at or now
        update_fields.extend(["status", "answered_at"])

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
    has_answered_token = any(token in event_type for token in ("answered", "connected", "in-progress", "inprogress"))
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
    waiting_for_pickup = call.status in {CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING}
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


def _get_campaign_timeline(campaign: Campaign, limit: int = 200) -> list[dict]:
    metadata = campaign.metadata if isinstance(campaign.metadata, dict) else {}
    timeline = metadata.get("timeline")
    if not isinstance(timeline, list):
        return []

    normalized: list[dict] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "at": str(item.get("at") or ""),
                "type": str(item.get("type") or "event"),
                "message": str(item.get("message") or ""),
                "details": item.get("details") if isinstance(item.get("details"), dict) else {},
                "call_id": item.get("call_id"),
                "lead_id": item.get("lead_id"),
            }
        )

    normalized.sort(key=lambda row: row.get("at") or "", reverse=True)
    return normalized[: max(1, min(int(limit or 200), 1000))]


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

    event = {
        "at": timezone.now().isoformat(),
        "type": str(event_type or "event"),
        "message": str(message or ""),
        "details": details if isinstance(details, dict) else {},
        "call_id": call.id if call else None,
        "lead_id": lead.id if lead else None,
    }

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
        timeline = metadata.get("timeline")
        if not isinstance(timeline, list):
            timeline = []
        timeline.append(event)
        metadata["timeline"] = timeline[-500:]
        locked_campaign.metadata = metadata
        locked_campaign.save(update_fields=["metadata", "updated_at"])

    campaign.metadata = metadata

    logger.info(
        "campaign_timeline campaign_id=%s type=%s message=%s details=%s call_id=%s lead_id=%s",
        campaign.id,
        event["type"],
        event["message"],
        json.dumps(event["details"], default=str),
        event["call_id"],
        event["lead_id"],
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
            and call.status in {CallStatus.QUEUED, CallStatus.DIALING, CallStatus.RINGING}
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
        if call.campaign_id and call.ended_at:
            _handle_campaign_call_terminal(call, auto_dispatch=False)
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

        dispatch_result = _initiate_campaign_call(campaign, campaign_lead)
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

        result = {"dispatched": False, "reason": "unable_to_dispatch"}
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

    max_call_duration_seconds = int(getattr(settings, "EXOTEL_MAX_CALL_DURATION_SECONDS", 60) or 60)
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
            if display_status == "no-answer":
                # Product requirement: after 60s no-pick, move to next contact (do not retry same lead).
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


def _to_call_outcome(status: str) -> str:
    value = str(status or "").strip().lower()
    if value in {"answered", "completed"}:
        return "connected"
    if value in {"no-answer", "no_answer"}:
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

    result = {
        "id": call.id,
        "public_id": str(call.public_id),
        "campaign_id": call.campaign_id,
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
        "payload_event_type": _extract_event_type(raw_payload),
        "payload_disposition": _extract_provider_disposition(raw_payload),
        "terminal_processed": bool(raw_payload.get("campaign_terminal_processed")),
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
