import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from uuid import uuid4

logger = logging.getLogger("dialer.campaign")


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def transcribe_recording_task(self, recording_id, force=False, language=None, reason=""):
    """
    Celery replacement for the daemon thread previously spawned by
    ``_schedule_recording_auto_transcription`` in views.py.
    """
    from .models import RecordingAsset, RecordingSource, TranscriptStatus
    from .views import (
        _debug_runtime,
        _is_terminal_call_for_transcription,
        _mark_recording_transcription_failed,
        _set_recording_transcription_progress,
        _transcribe_recording_asset,
        AUTO_TRANSCRIBE_LOCK_SECONDS,
    )

    lock_key = f"dialer:recording:auto_transcribe:{recording_id}"
    lock_token = f"{timezone.now().isoformat()}:{uuid4().hex}"
    if not cache.add(lock_key, lock_token, timeout=AUTO_TRANSCRIBE_LOCK_SECONDS):
        return

    try:
        fresh = (
            RecordingAsset.objects.select_related("call__lead", "call__agent")
            .filter(id=recording_id)
            .first()
        )
        if not fresh:
            return
        if fresh.call and fresh.source == RecordingSource.EXOTEL and not _is_terminal_call_for_transcription(fresh.call):
            return
        _set_recording_transcription_progress(
            fresh,
            6,
            stage="queued",
            status=TranscriptStatus.PROCESSING,
        )
        _debug_runtime(
            "auto_transcribe_recording_start",
            {
                "recording_id": fresh.id,
                "public_id": str(fresh.public_id),
                "status": str(fresh.transcript_status or ""),
                "reason": reason,
                "force": bool(force),
                "language": str(language or ""),
            },
        )
        result = _transcribe_recording_asset(fresh, force=force, language=language)
        _debug_runtime(
            "auto_transcribe_recording_result",
            {
                "recording_id": fresh.id,
                "public_id": str(fresh.public_id),
                "ok": bool(result.get("ok")),
                "error": str(result.get("error") or ""),
                "language": str(language or ""),
                "reason": reason,
                "force": bool(force),
            },
        )
    except Exception as exc:
        logger.exception("auto transcription failed for recording_id=%s", recording_id)
        fallback = RecordingAsset.objects.select_related("call").filter(id=recording_id).first()
        if fallback and fallback.transcript_status == TranscriptStatus.PROCESSING:
            _mark_recording_transcription_failed(fallback, f"auto_transcription_worker_error: {exc}")
    finally:
        current = cache.get(lock_key)
        if current == lock_token:
            cache.delete(lock_key)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def dispatch_campaign_retry_task(self, campaign_id, reason=""):
    """
    Celery replacement for the ``threading.Timer`` previously spawned by
    ``_schedule_campaign_dispatch_retry`` in views.py.
    """
    from .models import Campaign, CampaignStatus
    from .views import _dispatch_campaign_next_call, _log_campaign_event

    schedule_key = f"dialer:campaign_dispatch_retry:{campaign_id}"

    try:
        campaign = Campaign.objects.select_related("assigned_agent").filter(id=campaign_id).first()
        if not campaign or campaign.status != CampaignStatus.ACTIVE:
            return
        dispatch = _dispatch_campaign_next_call(campaign)
        _log_campaign_event(
            campaign,
            "dispatch_retry",
            "Scheduled dispatch retry attempted",
            details={
                "reason": reason or "retry",
                "dispatch": dispatch,
            },
        )
        if not dispatch.get("dispatched") and dispatch.get("reason") in {"cooldown_active", "dispatch_locked"}:
            retry_after = max(1, int(dispatch.get("retry_after_seconds") or 2))
            next_delay = retry_after + 1 if dispatch.get("reason") == "cooldown_active" else 2
            cache.delete(schedule_key)
            dispatch_campaign_retry_task.apply_async(
                args=[campaign.id],
                kwargs={"reason": f"{reason or 'retry'}:{dispatch.get('reason')}"},
                countdown=next_delay,
            )
    except Exception:
        logger.exception("scheduled dispatch retry failed for campaign_id=%s", campaign_id)
    finally:
        cache.delete(schedule_key)
