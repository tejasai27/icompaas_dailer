import uuid
from django.conf import settings
from django.db import models


class AgentStatus(models.TextChoices):
    AVAILABLE = "available", "Available"
    RINGING = "ringing", "Ringing"
    BUSY = "busy", "Busy"
    WRAP_UP = "wrap_up", "Wrap-Up"
    OFFLINE = "offline", "Offline"


class ProviderType(models.TextChoices):
    EXOTEL = "exotel", "Exotel"
    PLIVO = "plivo", "Plivo"


class CallOutcome(models.TextChoices):
    CONNECTED = "connected", "Connected"
    NO_ANSWER = "no_answer", "No Answer"
    BUSY = "busy", "Busy"
    VOICEMAIL = "voicemail", "Voicemail"
    MACHINE = "machine", "Machine"
    BAD_NUMBER = "bad_number", "Bad Number"
    INTERESTED = "interested", "Interested"
    NOT_INTERESTED = "not_interested", "Not Interested"
    FOLLOW_UP = "follow_up", "Follow Up"


class CallStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    DIALING = "dialing", "Dialing"
    RINGING = "ringing", "Ringing"
    HUMAN_DETECTED = "human_detected", "Human Detected"
    MACHINE_DETECTED = "machine_detected", "Machine Detected"
    BRIDGED = "bridged", "Bridged"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class AgentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=AgentStatus.choices, default=AgentStatus.OFFLINE)
    last_state_change = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.display_name


class Lead(models.Model):
    external_id = models.CharField(max_length=128, blank=True)
    full_name = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200, blank=True)
    phone_e164 = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    owner_hint = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone_e164})"


class LeadDialState(models.Model):
    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="dial_state")
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_outcome = models.CharField(max_length=32, choices=CallOutcome.choices, blank=True)
    is_completed = models.BooleanField(default=False)


class CallSession(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="calls")
    agent = models.ForeignKey(AgentProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    provider = models.CharField(max_length=20, choices=ProviderType.choices)
    provider_call_uuid = models.CharField(max_length=128, blank=True, db_index=True)
    status = models.CharField(max_length=32, choices=CallStatus.choices, default=CallStatus.QUEUED)
    started_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    wrap_up_deadline = models.DateTimeField(null=True, blank=True)
    recording_url = models.URLField(blank=True)
    transcript_url = models.URLField(blank=True)
    raw_provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["provider", "provider_call_uuid"]),
        ]


class CallDisposition(models.Model):
    call = models.OneToOneField(CallSession, on_delete=models.CASCADE, related_name="disposition")
    outcome = models.CharField(max_length=32, choices=CallOutcome.choices)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)


class CRMSyncLog(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    call = models.ForeignKey(CallSession, on_delete=models.CASCADE, related_name="crm_sync_logs")
    target = models.CharField(max_length=32, default="hubspot")
    status = models.CharField(
        max_length=16,
        choices=[
            (STATUS_PENDING, "Pending"),
            (STATUS_SUCCESS, "Success"),
            (STATUS_FAILED, "Failed"),
        ],
        default=STATUS_PENDING,
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["target", "status", "created_at"])]
