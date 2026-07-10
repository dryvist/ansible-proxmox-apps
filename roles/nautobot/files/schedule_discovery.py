"""Idempotently schedule the device-discovery Job on celery beat.

Registers a daily ``ScheduledJob`` bound to nautobot-device-onboarding's
"Sync Devices From Network" (``SSOTSyncDevices``) with the device-onboarding
SecretsGroup and the target set supplied in the environment.

Inert by design: SSOTSyncDevices sweeps SSH-CLI (netmiko) network platforms, so
it stays UNSCHEDULED unless real SSH targets + a platform are configured
(NAUTOBOT_ONBOARD_TARGETS + NAUTOBOT_ONBOARD_PLATFORM). Proxmox / iDRAC / UniFi
discovery via native APIs is a tracked follow-up, not this job.

Best-effort and self-guarding like schedule_export.py: prints
``DISCOVERY_SCHEDULED`` / ``DISCOVERY_EXISTS`` / ``DISCOVERY_SKIPPED <reason>``
and never raises.
"""
import os

from django.contrib.auth import get_user_model
from django.utils import timezone

JOB_NAME = "Sync Devices From Network"
SCHEDULE_NAME = "discovery-sync-devices-daily"
GROUP_NAME = os.environ.get("ONBOARDING_SECRETS_GROUP", "device-onboarding")

targets = os.environ.get("NAUTOBOT_ONBOARD_TARGETS", "").strip()
platform = os.environ.get("NAUTOBOT_ONBOARD_PLATFORM", "").strip()
location_name = os.environ.get("NAUTOBOT_ONBOARD_LOCATION", "homelab").strip()
port = int(os.environ.get("NAUTOBOT_ONBOARD_PORT", "22"))
hour = int(os.environ.get("NAUTOBOT_DISCOVERY_SCHEDULE_HOUR", "5"))
minute = int(os.environ.get("NAUTOBOT_DISCOVERY_SCHEDULE_MINUTE", "43"))

try:
    if not targets:
        print("DISCOVERY_SKIPPED no-targets")
        raise SystemExit(0)

    from nautobot.dcim.models import Location
    from nautobot.extras.choices import JobExecutionType
    from nautobot.extras.models import Job, ScheduledJob, SecretsGroup, Status

    job = Job.objects.filter(name=JOB_NAME).first()
    if job is None:
        print("DISCOVERY_SKIPPED job-not-registered")
        raise SystemExit(0)
    if not job.enabled:
        job.enabled = True
        job.save()

    group = SecretsGroup.objects.filter(name=GROUP_NAME).first()
    location = Location.objects.filter(name=location_name).first()
    approver = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()
    active = Status.objects.filter(name="Active").first()
    if not (group and location and approver and active):
        missing = [
            label
            for label, obj in (
                ("secrets-group", group),
                ("location", location),
                ("superuser", approver),
                ("active-status", active),
            )
            if obj is None
        ]
        print("DISCOVERY_SKIPPED missing:%s" % ",".join(missing))
        raise SystemExit(0)

    job_kwargs = {
        "location": str(location.pk),
        "ip_addresses": targets,
        "port": port,
        "timeout": 30,
        "secrets_group": str(group.pk),
        "platform": platform or None,
        "device_role": None,
        "device_status": str(active.pk),
        "interface_status": str(active.pk),
        "ip_address_status": str(active.pk),
        "namespace": None,
        "set_mgmt_only": True,
        "update_devices_without_primary_ip": False,
    }

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
            "kwargs": job_kwargs,
        },
    )
    print("DISCOVERY_SCHEDULED" if created else "DISCOVERY_EXISTS")
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001 - best-effort; never fail the converge
    print(f"DISCOVERY_SKIPPED {type(exc).__name__}: {exc}")
