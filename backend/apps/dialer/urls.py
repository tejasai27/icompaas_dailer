from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("agents/", views.list_agents, name="list-agents"),
    path("agents/<int:agent_id>/status/", views.update_agent_status, name="update-agent-status"),
    path("leads/", views.list_leads, name="list-leads"),
    path("leads/next/", views.next_lead, name="next-lead"),
    path("leads/upload/", views.upload_leads_csv, name="upload-leads-csv"),
    path("leads/manual/", views.create_manual_leads, name="create-manual-leads"),
    path("call-logs/", views.list_call_logs, name="list-call-logs"),
    path("call-logs/sync/exotel/", views.sync_exotel_call_logs, name="sync-exotel-call-logs"),
    path(
        "call-logs/<int:call_id>/trigger_transcription/",
        views.trigger_transcription,
        name="trigger-transcription",
    ),
    path("calls/start/exotel/", views.start_exotel_call, name="start-exotel-call"),
    path("webhooks/exotel/", views.exotel_webhook, name="exotel-webhook"),
]
