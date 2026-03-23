import os
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.telephony.base import DialRequest
from apps.telephony.exotel import ExotelProvider
from apps.telephony.factory import get_provider

from ..models import (
    AgentProfile,
    AgentStatus,
    Campaign,
    CallSession,
    CallStatus,
    Lead,
    ProviderType,
)
from ..services.call_utils import (
    _extract_event_type,
    _extract_provider_disposition,
    _flatten_payload_text,
    _parse_bool,
)
from ..services.hubspot_service import (
    _first_non_empty_text,
    _lookup_value,
    _normalize_hubspot_deal_id,
    _sync_call_to_hubspot,
)
from ..webhook_auth import verify_exotel_webhook
from ._helpers import (
    _active_call_not_ended_filter,
    _assign_runtime_exotel_wait_url,
    _debug_runtime,
    _load_json_body,
    _load_webhook_payload,
    _normalize_amd,
    _normalize_phone,
    _parse_json_like_dict,
    _parse_positive_int,
    _resolve_max_call_duration_seconds,
    logger,
)
from .campaign_views import (
    _handle_campaign_call_terminal,
    _log_campaign_event,
)


# ─── webhook metadata extraction ────────────────────────────────────
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


# ─── view functions ─────────────────────────────────────────────────
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
@verify_exotel_webhook
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
