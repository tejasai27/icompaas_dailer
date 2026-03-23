import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("icompaas_dialer")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Celery Beat schedule — server-side periodic tasks
app.conf.beat_schedule = {
    "tick-active-campaigns": {
        "task": "apps.dialer.tasks.tick_all_active_campaigns",
        "schedule": 5.0,  # every 5 seconds
    },
}
