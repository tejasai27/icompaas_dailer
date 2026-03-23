import json
import os
from datetime import datetime, timedelta
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.telephony.base import DialRequest
from apps.telephony.exotel import ExotelProvider
from apps.telephony.factory import get_provider

from ..models import (
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
from ..services.call_utils import (
    _derive_display_status,
    _duration_seconds_for_call,
    _extract_event_type,
    _extract_provider_disposition,
    _parse_bool,
)
from ..services.hubspot_service import (
    _first_non_empty_text,
    _lookup_value,
    _normalize_hubspot_deal_id,
    _sync_call_to_hubspot,
)
from ._helpers import (
    _active_call_not_ended_filter,
    _assign_runtime_exotel_wait_url,
    _debug_runtime,
    _extract_campaign_settings,
    _first_present,
    _load_json_body,
    _normalize_amd,
    _normalize_phone,
    _parse_non_negative_int,
    _parse_positive_int,
    _parse_provider_datetime,
    _resolve_max_call_duration_seconds,
    logger,
)
from .call_views import (
    _build_call_logs_summary,
    _serialize_call_log,
)


# ─── campaign settings helpers ───────────────────────────────────────
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


# ─── campaign serialization ──────────────────────────────────────────
def _serialize_campaign(campaign: Campaign) -> dict:
    counts = CampaignLead.objects.filter(campaign=campaign).aggregate(
        total=Count("id"),
        dialed=Count("id", filter=Q(attempt_count__gt=0)),
        pending=Count("id", filter=Q(status=CampaignLeadStatus.PENDING)),
        in_progress=Count("id", filter=Q(status=CampaignLeadStatus.IN_PROGRESS)),
        completed=Count("id", filter=Q(status=CampaignLeadStatus.COMPLETED)),
        failed=Count("id", filter=Q(status=CampaignLeadStatus.FAILED)),
    )
    total_contacts = counts["total"]
    dialed_contacts = counts["dialed"]
    pending_contacts = counts["pending"]
    in_progress_contacts = counts["in_progress"]
    completed_contacts = counts["completed"]
    failed_contacts = counts["failed"]

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


# ─── campaign queue/cooldown helpers ─────────────────────────────────
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


# ─── Exotel snapshot helpers ────────────────────────────────────────
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
        # Function-level import to avoid circular dependency with recording_views
        from .recording_views import _maybe_schedule_call_recording_transcription
        _maybe_schedule_call_recording_transcription(call, reason="exotel_snapshot")
    return True


# ─── provider end/answer confirmation ────────────────────────────────
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


# ─── campaign sync/poll helpers ──────────────────────────────────────
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


# ─── stuck in-progress recovery ──────────────────────────────────────
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


# ─── campaign dispatch ───────────────────────────────────────────────
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


# ─── terminal call handling ──────────────────────────────────────────
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

    from ..tasks import dispatch_campaign_retry_task
    dispatch_campaign_retry_task.apply_async(
        args=[campaign_id], kwargs={"reason": reason}, countdown=delay,
    )


# ─── campaign view functions ─────────────────────────────────────────
@csrf_exempt
def list_campaigns(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        return create_campaign(request)
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    status_filter = str(request.GET.get("status") or "").strip().lower()

    try:
        queryset = Campaign.objects.select_related("assigned_agent", "assigned_agent__user").order_by("-created_at")
        if status_filter and status_filter in {choice[0] for choice in CampaignStatus.choices}:
            queryset = queryset.filter(status=status_filter)

        campaigns = list(queryset)
        results = [_serialize_campaign(campaign) for campaign in campaigns]
        return JsonResponse({"count": len(results), "results": results})
    except (ProgrammingError, OperationalError) as exc:
        logger.exception("list_campaigns_failed: %s", exc)
        return JsonResponse(
            {
                "count": 0,
                "results": [],
                "warning": "campaign data unavailable",
            }
        )


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
