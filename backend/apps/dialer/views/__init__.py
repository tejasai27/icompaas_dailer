"""
views/ package — re-exports every public view function plus private
symbols consumed by tasks.py and other modules outside the package.

Usage unchanged:
    from . import views            -> views.health, views.list_agents, ...
    from .views import health      -> health(request)
    from .views import _debug_runtime  -> _debug_runtime(...)
"""

# ── _helpers (constants + utility functions used by tasks.py) ────────
from ._helpers import (  # noqa: F401
    AUTO_TRANSCRIBE_LOCK_SECONDS,
    _debug_runtime,
)

# ── health ───────────────────────────────────────────────────────────
from .health_views import (  # noqa: F401
    health,
)

# ── settings / integrations ──────────────────────────────────────────
from .settings_views import (  # noqa: F401
    clear_exotel_wait_audio,
    get_exotel_wait_audio,
    hubspot_settings,
    list_hubspot_records,
    sync_call_to_hubspot,
    test_hubspot_settings,
    upload_exotel_wait_audio,
)

# ── agents ───────────────────────────────────────────────────────────
from .agent_views import (  # noqa: F401
    create_agent,
    delete_agent,
    list_agents,
    update_agent,
    update_agent_status,
)

# ── campaigns ────────────────────────────────────────────────────────
from .campaign_views import (  # noqa: F401
    campaign_analytics,
    campaign_queue,
    campaign_tick,
    create_campaign,
    delete_campaign,
    dispatch_campaign,
    get_campaign,
    list_campaigns,
    pause_campaign,
    remove_campaign_contact,
    restart_campaign_from_first,
    resume_campaign,
    start_campaign,
    stop_campaign,
    # private symbols needed by tasks.py
    _dispatch_campaign_next_call,
    _log_campaign_event,
    _recover_stuck_in_progress_leads,
    _sync_campaign_open_calls,
)

# ── leads ────────────────────────────────────────────────────────────
from .lead_views import (  # noqa: F401
    bulk_delete_filtered_leads,
    bulk_delete_leads,
    create_manual_leads,
    delete_lead,
    list_contacts,
    list_leads,
    next_lead,
    update_lead,
    upload_leads_csv,
)

# ── call logs / sessions ─────────────────────────────────────────────
from .call_views import (  # noqa: F401
    get_call_session,
    hangup_call_session,
    list_call_logs,
    save_call_disposition,
    sync_exotel_call_logs,
    trigger_transcription,
)

# ── recordings / transcription ───────────────────────────────────────
from .recording_views import (  # noqa: F401
    get_recording,
    list_recordings,
    transcribe_recording,
    upload_recording,
    # private symbols needed by tasks.py
    _is_terminal_call_for_transcription,
    _mark_recording_transcription_failed,
    _set_recording_transcription_progress,
    _transcribe_recording_asset,
)

# ── webhooks ─────────────────────────────────────────────────────────
from .webhook_views import (  # noqa: F401
    exotel_webhook,
    start_exotel_call,
)
