from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("agents/", views.list_agents, name="list-agents"),
    path("agents/<int:agent_id>/status/", views.update_agent_status, name="update-agent-status"),
    path("leads/next/", views.next_lead, name="next-lead"),
    path("calls/start/exotel/", views.start_exotel_call, name="start-exotel-call"),
    path("webhooks/exotel/", views.exotel_webhook, name="exotel-webhook"),
]
