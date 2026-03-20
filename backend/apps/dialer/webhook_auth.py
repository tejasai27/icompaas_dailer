import functools
import hashlib
import hmac
import logging
import os

from django.http import JsonResponse

logger = logging.getLogger("dialer.webhook_auth")


def verify_exotel_webhook(view_func):
    """Decorator that verifies Exotel webhook authenticity.

    When ``EXOTEL_WEBHOOK_SECRET`` is set, incoming requests must satisfy at
    least one of the following:

    1. An ``X-Exotel-Signature`` header whose value equals the HMAC-SHA256
       hex-digest of the raw request body computed with the shared secret.
    2. A ``token`` query-string parameter that matches the shared secret.

    If the environment variable is empty or missing the decorator is a no-op
    (backwards compatible) but a warning is logged once.
    """

    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        secret = os.getenv("EXOTEL_WEBHOOK_SECRET", "").strip()

        if not secret:
            logger.warning(
                "EXOTEL_WEBHOOK_SECRET is not configured — webhook "
                "signature verification is disabled. Set this variable "
                "in production to protect the endpoint."
            )
            return view_func(request, *args, **kwargs)

        # Method 1: HMAC-SHA256 signature header
        signature_header = request.headers.get("X-Exotel-Signature", "").strip()
        if signature_header:
            expected = hmac.new(
                secret.encode("utf-8"),
                request.body,
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(signature_header, expected):
                return view_func(request, *args, **kwargs)

        # Method 2: shared-secret token in query string
        token_param = request.GET.get("token", "").strip()
        if token_param and hmac.compare_digest(token_param, secret):
            return view_func(request, *args, **kwargs)

        logger.warning(
            "exotel_webhook_auth_failed path=%s remote=%s",
            request.path,
            request.META.get("REMOTE_ADDR"),
        )
        return JsonResponse({"detail": "Invalid webhook signature."}, status=403)

    return _wrapped
