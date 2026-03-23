import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import (
    AgentProfile,
    AgentStatus,
    CallSession,
    CallStatus,
)
from ._helpers import (
    _active_call_not_ended_filter,
    _load_json_body,
    logger,
)


def _serialize_agent(agent: AgentProfile) -> dict:
    user = getattr(agent, "user", None)
    username = ""
    email = ""
    if user:
        username_field = getattr(user, "USERNAME_FIELD", "username")
        username = str(getattr(user, username_field, "") or "")
        email = str(getattr(user, "email", "") or "")

    return {
        "id": agent.id,
        "display_name": agent.display_name,
        "status": agent.status,
        "user_id": agent.user_id,
        "username": username,
        "email": email,
    }


def _username_base_from_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return cleaned[:40] if cleaned else "sdr"


def _build_unique_username(User: type, base: str, exclude_user_id: int | None = None) -> str:
    username_field = str(getattr(User, "USERNAME_FIELD", "username"))
    candidate = _username_base_from_text(base)
    suffix = 1
    while True:
        queryset = User.objects.filter(**{username_field: candidate})
        if exclude_user_id:
            queryset = queryset.exclude(id=exclude_user_id)
        if not queryset.exists():
            return candidate
        candidate = f"{_username_base_from_text(base)}_{suffix}"
        suffix += 1


@require_GET
def list_agents(request: HttpRequest) -> JsonResponse:
    try:
        agents = AgentProfile.objects.select_related("user").order_by("id")
        return JsonResponse(
            {
                "agents": [_serialize_agent(agent) for agent in agents]
            }
        )
    except (ProgrammingError, OperationalError) as exc:
        logger.exception("list_agents_failed: %s", exc)
        return JsonResponse(
            {
                "agents": [],
                "warning": "agent data unavailable",
            }
        )


@csrf_exempt
@require_POST
def create_agent(request: HttpRequest) -> JsonResponse:
    payload = _load_json_body(request)
    display_name = str(payload.get("display_name") or payload.get("name") or "").strip()
    if not display_name:
        return JsonResponse({"error": "display_name is required"}, status=400)

    status = str(payload.get("status") or AgentStatus.OFFLINE).strip().lower()
    valid_statuses = {choice[0] for choice in AgentProfile._meta.get_field("status").choices}
    if status not in valid_statuses:
        return JsonResponse({"error": "invalid status"}, status=400)

    email = str(payload.get("email") or "").strip()
    username_input = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "").strip()

    User = get_user_model()
    base_username = username_input or _username_base_from_text(email.split("@")[0] if "@" in email else display_name)
    username = _build_unique_username(User, base_username)

    user_kwargs: dict[str, object] = {User.USERNAME_FIELD: username}
    if hasattr(User, "email"):
        user_kwargs["email"] = email
    if hasattr(User, "first_name"):
        user_kwargs["first_name"] = display_name

    try:
        if password:
            user = User.objects.create_user(password=password, **user_kwargs)
        else:
            user = User.objects.create_user(password=None, **user_kwargs)
            user.set_unusable_password()
            user.save(update_fields=["password"])
    except IntegrityError:
        return JsonResponse({"error": "user_creation_failed"}, status=400)

    agent = AgentProfile.objects.create(
        user=user,
        display_name=display_name,
        status=status,
    )
    return JsonResponse({"ok": True, "agent": _serialize_agent(agent)}, status=201)


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
@require_POST
def update_agent(request: HttpRequest, agent_id: int) -> JsonResponse:
    payload = _load_json_body(request)
    agent = get_object_or_404(AgentProfile.objects.select_related("user"), id=agent_id)
    user = agent.user

    display_name = str(payload.get("display_name") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    email = str(payload.get("email") or "").strip()
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "").strip()

    if status:
        valid_statuses = {choice[0] for choice in AgentProfile._meta.get_field("status").choices}
        if status not in valid_statuses:
            return JsonResponse({"error": "invalid status"}, status=400)

    User = get_user_model()

    with transaction.atomic():
        agent = AgentProfile.objects.select_related("user").select_for_update().get(id=agent.id)
        user = agent.user

        agent_update_fields: list[str] = []
        if display_name and display_name != agent.display_name:
            agent.display_name = display_name
            agent_update_fields.append("display_name")

        if status and status != agent.status:
            agent.status = status
            agent_update_fields.extend(["status", "last_state_change"])

        if agent_update_fields:
            agent.save(update_fields=list(dict.fromkeys(agent_update_fields)))

        user_update_fields: list[str] = []
        if hasattr(user, "email") and email and email != getattr(user, "email", ""):
            user.email = email
            user_update_fields.append("email")

        if username:
            current_username = str(getattr(user, User.USERNAME_FIELD, "") or "")
            if username != current_username:
                safe_username = _build_unique_username(User, username, exclude_user_id=user.id)
                setattr(user, User.USERNAME_FIELD, safe_username)
                user_update_fields.append(User.USERNAME_FIELD)

        if password:
            user.set_password(password)
            user_update_fields.append("password")

        if user_update_fields:
            user.save(update_fields=list(dict.fromkeys(user_update_fields)))

    agent.refresh_from_db()
    return JsonResponse({"ok": True, "agent": _serialize_agent(agent)})


@csrf_exempt
@require_POST
def delete_agent(request: HttpRequest, agent_id: int) -> JsonResponse:
    agent = get_object_or_404(AgentProfile, id=agent_id)
    active_call_exists = CallSession.objects.filter(
        agent_id=agent.id,
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
            {"error": "agent_call_in_progress", "message": "This SDR has an active call"},
            status=409,
        )

    agent_name = agent.display_name
    user_id = agent.user_id
    agent.delete()
    return JsonResponse({"ok": True, "deleted": True, "agent_id": agent_id, "display_name": agent_name, "user_id": user_id})
