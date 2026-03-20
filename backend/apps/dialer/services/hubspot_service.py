"""
HubSpot integration service functions extracted from views.py.

All private helper functions that interact with the HubSpot CRM API live here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re

from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

import requests

from ..models import (
    CallDisposition,
    CallSession,
    CRMSyncLog,
    HubSpotDealAssociationMode,
    HubSpotIntegrationSettings,
)
from .call_utils import (
    _derive_display_status,
    _duration_seconds_for_call,
    _parse_bool,
)

logger = logging.getLogger("dialer.campaign")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HUBSPOT_API_BASE = "https://api.hubapi.com"
HUBSPOT_TIMEOUT_SECONDS = max(3.0, float(os.getenv("HUBSPOT_TIMEOUT_SECONDS", "12") or 12))

# Module-level cache for disposition deal-field availability.
_CALL_DISPOSITION_DEAL_FIELDS_AVAILABLE: bool | None = None


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Shared helpers (used by both HubSpot and views)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HubSpot settings helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# HubSpot API helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Deal helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Call / Task body builders
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Sync signature / logging / state
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main sync orchestrator
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


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
