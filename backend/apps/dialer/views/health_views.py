from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


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
