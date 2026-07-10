"""Run the SSoT seed jobs (and optionally the export) once, synchronously.

Run via ``nautobot-server shell --interface python`` (same mechanism as
superuser_bootstrap.py / schedule_export.py). For each seed job: enable it,
enqueue it to the running worker, then poll its JobResult to a terminal state.
The worker executes with the units' EnvironmentFile (nautobot.env), so it has
the seed-file path and export S3 credentials without this script passing them.

Ordering matters: VLANs/Prefixes first (IP reservations attach under a parent
prefix), then IPs, DCIM, nodes, and virtualization last.

Version-defensive like schedule_export.py: prints a per-job marker and never
raises, so one job's quirk cannot abort the converge. Markers:
``JOB_DONE <name> <status>`` / ``JOB_SKIPPED <name> <reason>`` /
``JOB_ERROR <name> <detail>`` / ``JOB_TIMEOUT <name>``.
"""
import os
import time

from django.contrib.auth import get_user_model
from nautobot.extras.models import Job, JobResult

# SSoT DataSource jobs default to a dry run — they need dryrun=False to commit.
SSOT_JOBS = [
    "Seed VLANs and Prefixes",
    "Seed IP Addresses and Reservations",
    "Seed DCIM Racks and Devices",
    "Seed Proxmox Node Facts",
    "SSoT: Virtualization (Proxmox guests)",
]
# Plain Jobs (no dryrun var) — enqueued without job kwargs.
PLAIN_JOBS = ["Configure Device Onboarding Targets"]

SEED_JOBS = SSOT_JOBS + PLAIN_JOBS
if os.environ.get("NAUTOBOT_RUN_EXPORT", "").lower() in ("1", "true", "yes"):
    SEED_JOBS.append("Export Nautobot Inventory to S3")

# Celery terminal states (Nautobot JobResult.status mirrors these).
TERMINAL = {"SUCCESS", "FAILURE", "REVOKED"}
TIMEOUT = int(os.environ.get("NAUTOBOT_JOB_TIMEOUT", "300"))

approver = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()


def run_one(name):
    """Enable, enqueue, and poll a single job by display name.

    SSoT DataSource jobs default to a dry run (compute diffs, commit nothing);
    pass ``dryrun=False`` so the additive sync actually persists. Plain Jobs
    (export, onboarding setup) have no such var, so they get no job kwargs.
    """
    job = Job.objects.filter(name=name).first()
    if job is None:
        print("JOB_SKIPPED", name, "not-registered")
        return
    if not job.enabled:
        job.enabled = True
        job.save()
    kwargs = {"dryrun": False} if name in SSOT_JOBS else {}
    try:
        result = JobResult.enqueue_job(job, approver, **kwargs)
    except Exception as exc:  # noqa: BLE001 - enqueue signature is version-sensitive
        print("JOB_ERROR", name, "enqueue:%s" % exc)
        return
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        result.refresh_from_db()
        status = str(getattr(result, "status", "")).upper()
        if status in TERMINAL:
            print("JOB_DONE", name, status)
            return
        time.sleep(3)
    print("JOB_TIMEOUT", name)


for job_name in SEED_JOBS:
    run_one(job_name)
