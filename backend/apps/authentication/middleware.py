import re

from django.conf import settings
from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

# Paths that don't require authentication
AUTH_EXEMPT_PATTERNS = [
    re.compile(r"/auth/login/$"),
    re.compile(r"/auth/refresh/$"),
    re.compile(r"/auth/logout/$"),
    re.compile(r"/health/$"),
    re.compile(r"/webhooks/"),
    re.compile(r"^/admin/"),
    re.compile(r"^/static/"),
    re.compile(r"^/media/"),
]


class JWTAuthenticationMiddleware:
    """Authenticate requests using JWT from HttpOnly cookies.

    Falls back to the Authorization header so API clients (e.g. curl,
    Postman) still work.

    When AUTH_ENFORCEMENT_ENABLED is False (default), all requests are
    allowed through — auth is bypassed for dev/demo mode.
    When True, unauthenticated requests to non-exempt paths are rejected.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt_auth = JWTAuthentication()

    def _is_exempt(self, path):
        return any(pattern.search(path) for pattern in AUTH_EXEMPT_PATTERNS)

    def __call__(self, request):
        # If enforcement is off, let everything through (dev/demo mode)
        if not getattr(settings, "AUTH_ENFORCEMENT_ENABLED", False):
            return self.get_response(request)

        if self._is_exempt(request.path):
            return self.get_response(request)

        user = None

        # 1) Try cookie-based auth
        access_token = request.COOKIES.get(settings.AUTH_ACCESS_COOKIE)
        if access_token:
            try:
                validated = self.jwt_auth.get_validated_token(access_token)
                user = self.jwt_auth.get_user(validated)
            except (InvalidToken, TokenError):
                pass

        # 2) Fallback: Authorization header
        if user is None:
            auth_header = request.META.get("HTTP_AUTHORIZATION", "")
            if auth_header.startswith("Bearer "):
                token_str = auth_header.split(" ", 1)[1]
                try:
                    validated = self.jwt_auth.get_validated_token(token_str)
                    user = self.jwt_auth.get_user(validated)
                except (InvalidToken, TokenError):
                    pass

        if user is not None:
            request.user = user
            return self.get_response(request)

        # No valid auth found — reject
        return JsonResponse(
            {"detail": "Authentication credentials were not provided."},
            status=401,
        )
