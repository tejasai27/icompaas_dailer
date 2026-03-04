from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dialer", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Campaign",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("paused", "Paused"),
                            ("completed", "Completed"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "dialing_mode",
                    models.CharField(
                        choices=[("power", "Power Dialer"), ("dynamic", "Dynamic Dialer")],
                        default="power",
                        max_length=20,
                    ),
                ),
                ("agent_phone", models.CharField(blank=True, max_length=20)),
                ("caller_id", models.CharField(blank=True, max_length=20)),
                ("delay_between_calls", models.PositiveIntegerField(default=15)),
                ("max_retries", models.PositiveIntegerField(default=2)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("paused_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_dispatch_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_agent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="campaigns",
                        to="dialer.agentprofile",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["status", "created_at"], name="dialer_camp_status_70cb14_idx")],
            },
        ),
        migrations.AddField(
            model_name="callsession",
            name="campaign",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="calls",
                to="dialer.campaign",
            ),
        ),
        migrations.CreateModel(
            name="CampaignLead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("queue_order", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("in_progress", "In Progress"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("last_outcome", models.CharField(blank=True, max_length=32)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "campaign",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="campaign_leads", to="dialer.campaign"),
                ),
                (
                    "last_call",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="dialer.callsession",
                    ),
                ),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="campaign_links", to="dialer.lead")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["campaign", "status", "next_attempt_at"], name="dialer_camp_campaig_0e7c8c_idx"),
                    models.Index(fields=["campaign", "queue_order", "id"], name="dialer_camp_campaig_43c882_idx"),
                ],
                "unique_together": {("campaign", "lead")},
            },
        ),
    ]
