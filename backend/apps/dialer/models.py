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


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    ARCHIVED = "archived", "Archived"


class CampaignDialingMode(models.TextChoices):
    POWER = "power", "Power Dialer"
    DYNAMIC = "dynamic", "Dynamic Dialer"


class CampaignLeadStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In Progress"
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


class Campaign(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT)
    dialing_mode = models.CharField(
        max_length=20,
        choices=CampaignDialingMode.choices,
        default=CampaignDialingMode.POWER,
    )
    assigned_agent = models.ForeignKey(
        AgentProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="campaigns",
    )
    agent_phone = models.CharField(max_length=20, blank=True)
    caller_id = models.CharField(max_length=20, blank=True)
    delay_between_calls = models.PositiveIntegerField(default=15)
    max_retries = models.PositiveIntegerField(default=2)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_dispatch_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.name


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
    campaign = models.ForeignKey(
        Campaign,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="calls",
    )
    raw_provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["provider", "provider_call_uuid"]),
        ]


class CampaignLead(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="campaign_leads")
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="campaign_links")
    queue_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=CampaignLeadStatus.choices,
        default=CampaignLeadStatus.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_outcome = models.CharField(max_length=32, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_call = models.ForeignKey(CallSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("campaign", "lead")
        indexes = [
            models.Index(fields=["campaign", "status", "next_attempt_at"]),
            models.Index(fields=["campaign", "queue_order", "id"]),
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


class RecordingSource(models.TextChoices):
    EXOTEL = "exotel", "Exotel"
    UPLOAD = "upload", "Upload"


class TranscriptStatus(models.TextChoices):
    NONE = "none", "None"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class RecordingAsset(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    source = models.CharField(max_length=20, choices=RecordingSource.choices)
    call = models.OneToOneField(
        CallSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recording_asset",
    )
    title = models.CharField(max_length=255, blank=True)
    audio_file = models.FileField(upload_to="dialer/recordings/", blank=True)
    external_audio_url = models.URLField(blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    transcript_status = models.CharField(max_length=20, choices=TranscriptStatus.choices, default=TranscriptStatus.NONE)
    transcript_text = models.TextField(blank=True)
    transcript_segments = models.JSONField(default=list, blank=True)
    transcript_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "created_at"]),
            models.Index(fields=["transcript_status", "created_at"]),
        ]

    def __str__(self) -> str:
        if self.title:
            return self.title
        return f"{self.source}:{self.public_id}"
