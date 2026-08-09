"""Idempotently schedule the S3 export Job on celery beat.

Run via ``nautobot-server shell --interface python``. Creates a daily
``ScheduledJob`` bound to the export Job at the hour/minute given in the
environment. The ScheduledJob ORM surface is version-sensitive, so a failure
prints a ``SCHEDULE_SKIPPED`` marker with the reason instead of raising a
traceback through the shell.

``SCHEDULE_SKIPPED`` is not a benign outcome. The caller in ``tasks/main.yml``
asserts on these markers and fails the converge, because a missing schedule
means the export — and therefore the only thing that publishes this instance's
inventory — silently stops. Prints ``SCHEDULE_CREATED`` / ``SCHEDULE_REENABLED``
/ ``SCHEDULE_EXISTS`` on success.
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
                },
            )
            if created:
                print("SCHEDULE_CREATED")
            elif not obj.enabled:
                # get_or_create only applies `defaults` when it creates. A
                # schedule disabled in the UI therefore survived every converge
                # while this reported SCHEDULE_EXISTS — present, reconciled, and
                # not running. Reconcile the field the converge claims to own.
                obj.enabled = True
                obj.save()
                print("SCHEDULE_REENABLED")
            else:
                print("SCHEDULE_EXISTS")
except Exception as exc:  # noqa: BLE001 - best-effort; never fail the converge
    print(f"SCHEDULE_SKIPPED {type(exc).__name__}: {exc}")
