import json
import logging

from django.contrib.auth import authenticate
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

logger = logging.getLogger("authentication")


def _user_payload(user) -> dict:
    """Build the user dict the frontend expects."""
    profile = getattr(user, "agentprofile", None)
    full_name = (
        profile.display_name
        if profile
        else user.get_full_name() or user.username
    )
    role = "admin" if (user.is_superuser or user.is_staff) else "agent"
    return {
        "username": user.username,
        "full_name": full_name,
        "role": role,
    }


@csrf_exempt
@require_POST
def login_view(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))

    if not username or not password:
        return JsonResponse(
            {"detail": "Username and password are required."}, status=400
        )

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    refresh = RefreshToken.for_user(user)

    return JsonResponse(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": _user_payload(user),
        }
    )


@csrf_exempt
@require_POST
def refresh_view(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    token_str = str(body.get("refresh", "")).strip()
    if not token_str:
        return JsonResponse({"detail": "Refresh token is required."}, status=400)

    try:
        token = RefreshToken(token_str)
    except TokenError:
        return JsonResponse(
            {"detail": "Token is invalid or expired."}, status=401
        )

    return JsonResponse({"access": str(token.access_token)})


@csrf_exempt
@require_GET
def me_view(request: HttpRequest) -> JsonResponse:
    if not request.user or not request.user.is_authenticated:
        return JsonResponse(
            {"detail": "Authentication credentials were not provided."},
            status=401,
        )
    return JsonResponse({"user": _user_payload(request.user)})
