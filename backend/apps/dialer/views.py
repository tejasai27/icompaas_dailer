import json
import os
from datetime import timedelta
from urllib.parse import parse_qsl

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
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
                "max_duration_seconds": max_call_duration_seconds,
            }
        },
    )

    dial_request = DialRequest(
        lead_id=lead.id,
        to_number=lead.phone_e164,
        from_number=agent_phone,
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
