"""Idempotently schedule the Proxmox drive sync on celery beat."""
import os

from django.contrib.auth import get_user_model
from django.utils import timezone

JOB_NAME = "Sync Drive Inventory from Proxmox"
SCHEDULE_NAME = "sync-proxmox-drives-daily"
HOUR = 4
MINUTE = 43

if not all(
    os.environ.get(name, "").strip()
    for name in (
        "NAUTOBOT_PROXMOX_API_URL",
        "NAUTOBOT_PROXMOX_TOKEN_ID",
        "NAUTOBOT_PROXMOX_TOKEN_SECRET",
        "NAUTOBOT_PROXMOX_CA",
    )
):
    print("DRIVES_SCHEDULE_SKIPPED missing-config")
else:
    try:
        from nautobot.extras.choices import JobExecutionType
        from nautobot.extras.models import Job, ScheduledJob

        job = Job.objects.filter(name=JOB_NAME).first()
        approver = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
        if job is None:
            print("DRIVES_SCHEDULE_SKIPPED job-not-registered")
        elif approver is None:
            print("DRIVES_SCHEDULE_SKIPPED no-superuser")
        else:
            if not job.enabled:
                job.enabled = True
                job.save()
            obj, created = ScheduledJob.objects.get_or_create(
                name=SCHEDULE_NAME,
                defaults={
                    "job_model": job,
                    "task": job.class_path,
                    "interval": JobExecutionType.TYPE_CUSTOM,
                    "crontab": f"{MINUTE} {HOUR} * * *",
                    "user": approver,
                    "start_time": timezone.now(),
                    "enabled": True,
                },
            )
            if created:
                print("DRIVES_SCHEDULE_CREATED")
            elif not obj.enabled:
                obj.enabled = True
                obj.save()
                print("DRIVES_SCHEDULE_REENABLED")
            else:
                print("DRIVES_SCHEDULE_EXISTS")
    except Exception as exc:  # noqa: BLE001 - shell caller checks the marker
        print(f"DRIVES_SCHEDULE_SKIPPED {type(exc).__name__}: {exc}")
