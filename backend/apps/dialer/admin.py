from django.contrib import admin
from .models import AgentProfile, CallDisposition, CallSession, CRMSyncLog, Lead, LeadDialState


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "display_name", "status", "last_state_change")
    list_filter = ("status",)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "phone_e164", "company_name", "created_at")
    search_fields = ("full_name", "phone_e164", "company_name")


@admin.register(LeadDialState)
class LeadDialStateAdmin(admin.ModelAdmin):
    list_display = ("lead", "attempt_count", "last_outcome", "is_completed")
    list_filter = ("is_completed", "last_outcome")


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display = ("public_id", "provider", "status", "lead", "agent", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("provider_call_uuid",)


@admin.register(CallDisposition)
class CallDispositionAdmin(admin.ModelAdmin):
    list_display = ("call", "outcome", "created_by", "created_at")
    list_filter = ("outcome",)


@admin.register(CRMSyncLog)
class CRMSyncLogAdmin(admin.ModelAdmin):
    list_display = ("id", "call", "target", "status", "retry_count", "created_at")
    list_filter = ("target", "status")
