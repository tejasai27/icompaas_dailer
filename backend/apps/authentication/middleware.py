import logging

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from rest_framework_simplejwt.tokens import AccessToken, TokenError

logger = logging.getLogger("authentication")

User = get_user_model()

# Paths that do NOT require a valid JWT token.
AUTH_EXEMPT_PREFIXES = (
    "/api/v1/dialer/health/",
    "/api/v1/dialer/webhooks/",
    "/api/v1/dialer/auth/login/",
    "/api/v1/dialer/auth/refresh/",
    "/admin/",
    "/media/",
    "/static/",
)


class JWTAuthenticationMiddleware:
    """Enforce JWT Bearer-token authentication on all API endpoints.

    Requests whose path starts with one of AUTH_EXEMPT_PREFIXES are passed
    through without authentication.  All other requests must carry a valid
    ``Authorization: Bearer <token>`` header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Let exempt paths through (health, webhooks, login, refresh, admin, media).
        if any(request.path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES):
            return self.get_response(request)

        # Extract the Authorization header.
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return JsonResponse(
                {"detail": "Authentication credentials were not provided."},
                status=401,
            )

        raw_token = auth_header[7:]  # strip "Bearer "

        # Validate the token.
        try:
            validated = AccessToken(raw_token)
        except TokenError:
            return JsonResponse(
                {"detail": "Token is invalid or expired."},
                status=401,
            )

        # Look up the user.
        user_id = validated.get("user_id")
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            return JsonResponse(
                {"detail": "User not found or inactive."},
                status=401,
            )

        # Attach the authenticated user to the request.
        request.user = user
        request._jwt_authenticated = True

        return self.get_response(request)
