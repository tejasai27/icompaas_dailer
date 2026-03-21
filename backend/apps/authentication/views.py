import json
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token as get_csrf_token
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
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


def _set_auth_cookies(response: JsonResponse, access: str, refresh: str) -> JsonResponse:
    """Set access and refresh tokens as HttpOnly cookies."""
    access_max_age = int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    refresh_max_age = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

    response.set_cookie(
        settings.AUTH_ACCESS_COOKIE,
        access,
        max_age=access_max_age,
        httponly=settings.AUTH_COOKIE_HTTPONLY,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE,
        refresh,
        max_age=refresh_max_age,
        httponly=settings.AUTH_COOKIE_HTTPONLY,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )
    return response


def _clear_auth_cookies(response: JsonResponse) -> JsonResponse:
    """Delete access and refresh token cookies."""
    response.delete_cookie(settings.AUTH_ACCESS_COOKIE, path=settings.AUTH_COOKIE_PATH)
    response.delete_cookie(settings.AUTH_REFRESH_COOKIE, path=settings.AUTH_COOKIE_PATH)
    return response


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
    if user is None:
        User = get_user_model()
        lookup = {User.USERNAME_FIELD: username}
        existing_user = User.objects.filter(**lookup).first()
        if existing_user is not None:
            if not existing_user.has_usable_password():
                return JsonResponse(
                    {"detail": "Password is not set for this account."},
                    status=401,
                )
            if not existing_user.is_active:
                return JsonResponse({"detail": "Account is inactive."}, status=401)
        return JsonResponse({"detail": "Invalid credentials."}, status=401)

    if not user.is_active:
        return JsonResponse({"detail": "Account is inactive."}, status=401)

    refresh = RefreshToken.for_user(user)
    access_token = str(refresh.access_token)
    refresh_token = str(refresh)

    response = JsonResponse({"user": _user_payload(user)})
    _set_auth_cookies(response, access_token, refresh_token)

    # Ensure CSRF cookie is set for subsequent requests
    get_csrf_token(request)

    return response


@csrf_exempt
@require_POST
def refresh_view(request: HttpRequest) -> JsonResponse:
    # Read refresh token from cookie (fallback to body for backwards compat)
    token_str = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE, "")

    if not token_str:
        try:
            body = json.loads(request.body)
            token_str = str(body.get("refresh", "")).strip()
        except (json.JSONDecodeError, ValueError):
            pass

    if not token_str:
        return JsonResponse({"detail": "Refresh token is required."}, status=400)

    try:
        token = RefreshToken(token_str)
    except TokenError:
        response = JsonResponse(
            {"detail": "Token is invalid or expired."}, status=401
        )
        _clear_auth_cookies(response)
        return response

    new_access = str(token.access_token)
    response = JsonResponse({"detail": "Token refreshed."})
    # Update access cookie, keep refresh cookie
    response.set_cookie(
        settings.AUTH_ACCESS_COOKIE,
        new_access,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        httponly=settings.AUTH_COOKIE_HTTPONLY,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )
    return response


@require_POST
def logout_view(request: HttpRequest) -> JsonResponse:
    # Blacklist the refresh token if possible
    token_str = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE, "")
    if token_str:
        try:
            token = RefreshToken(token_str)
            token.blacklist()
        except (TokenError, AttributeError):
            # blacklist() not available if token_blacklist app not installed
            pass

    response = JsonResponse({"detail": "Logged out."})
    _clear_auth_cookies(response)
    return response


@ensure_csrf_cookie
@require_GET
def me_view(request: HttpRequest) -> JsonResponse:
    if request.user and request.user.is_authenticated:
        return JsonResponse({"user": _user_payload(request.user)})

    # When auth enforcement is disabled, return a guest user so the
    # frontend can render the app without requiring login.
    if not getattr(settings, "AUTH_ENFORCEMENT_ENABLED", False):
        return JsonResponse({
            "user": {
                "username": "guest",
                "full_name": "Guest User",
                "role": "admin",
            }
        })

    return JsonResponse(
        {"detail": "Authentication credentials were not provided."},
        status=401,
    )
