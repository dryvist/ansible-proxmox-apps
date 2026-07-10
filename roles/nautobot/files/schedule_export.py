"""Idempotently schedule the S3 export Job on celery beat.

Run via ``nautobot-server shell --interface python``. Creates a daily
``ScheduledJob`` bound to the export Job at the hour/minute given in the
environment. Best-effort and self-guarding: the ScheduledJob ORM surface is
version-sensitive, so any failure prints a ``SCHEDULE_SKIPPED`` marker with the
reason rather than aborting the converge — the schedule can be finalized in the
UI at cutover. Prints ``SCHEDULE_CREATED`` / ``SCHEDULE_EXISTS`` on success.
"""
import os

from django.contrib.auth import get_user_model
from django.utils import timezone

JOB_NAME = "Export Nautobot Inventory to S3"
SCHEDULE_NAME = "export-nautobot-daily"

hour = int(os.environ.get("NAUTOBOT_EXPORT_SCHEDULE_HOUR", "6"))
minute = int(os.environ.get("NAUTOBOT_EXPORT_SCHEDULE_MINUTE", "17"))

try:
    from nautobot.extras.choices import JobExecutionType
    from nautobot.extras.models import Job, ScheduledJob

    job = Job.objects.filter(name=JOB_NAME).first()
    if job is None:
        print("SCHEDULE_SKIPPED job-not-registered")
    else:
        if not job.enabled:
            job.enabled = True
            job.save()

        approver = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
        if approver is None:
            print("SCHEDULE_SKIPPED no-superuser")
        else:
            obj, created = ScheduledJob.objects.get_or_create(
                name=SCHEDULE_NAME,
                defaults={
                    "job_model": job,
                    "task": job.class_path,
                    "interval": JobExecutionType.TYPE_CUSTOM,
                    "crontab": f"{minute} {hour} * * *",
                    "user": approver,
                    "start_time": timezone.now(),
                    "enabled": True,
                    "approval_required": False,
                },
            )
            print("SCHEDULE_CREATED" if created else "SCHEDULE_EXISTS")
except Exception as exc:  # noqa: BLE001 - best-effort; never fail the converge
    print(f"SCHEDULE_SKIPPED {type(exc).__name__}: {exc}")
