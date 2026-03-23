import csv
import io

from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import (
    Campaign,
    CallSession,
    CallStatus,
    Lead,
    LeadDialState,
)
from ..services.call_utils import _parse_bool
from ._helpers import (
    _active_call_not_ended_filter,
    _extract_campaign_settings,
    _load_json_body,
    _normalize_phone,
    _parse_positive_int,
    _pick_value,
    logger,
)
from .campaign_views import (
    _attach_leads_to_campaign,
    _campaign_settings_from_campaign,
    _log_campaign_event,
)


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

    try:
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
    except (ProgrammingError, OperationalError) as exc:
        logger.exception("list_leads_failed: %s", exc)
        return JsonResponse(
            {
                "count": 0,
                "page": page,
                "page_size": page_size,
                "results": [],
                "warning": "lead data unavailable",
            }
        )


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
