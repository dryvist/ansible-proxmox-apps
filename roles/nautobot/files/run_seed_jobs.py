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
import json
import os
import sys
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
# Hardware runs after DCIM: a component installed in a chassis needs that
# chassis to exist as a Device first, or it is filed as a spare instead.
PLAIN_JOBS = ["Seed Hardware Inventory", "Configure Device Onboarding Targets"]

SEED_JOBS = SSOT_JOBS + PLAIN_JOBS
if os.environ.get("NAUTOBOT_RUN_EXPORT", "").lower() in ("1", "true", "yes"):
    SEED_JOBS.append("Export Nautobot Inventory to S3")

# A seed slice may legitimately be absent: seed_sources.yml supports a partial
# bundle and promises that "existing Nautobot objects of that kind are retained".
# That promise has to be STRUCTURAL. Running a job against an empty source loads
# an empty source adapter, and DiffSync then computes a diff that is all
# `delete` — retention today rests only on delete being a no-op on these models,
# so adding one model without that no-op silently wipes its slice.
#
# So a job whose slice carries no rows is dropped from the run entirely. The
# drive sync is the sharpest case (it is the one seed job that DOES delete), but
# the rule is the same for every slice-backed job.
#
# Dropped here, BEFORE the loop, never through run_one(): its JOB_SKIPPED path
# returns False, which would fail the converge and break the very partial-bundle
# mode this protects.
#
# The drive sync also refuses an empty slice inside the job itself, which is not
# redundant: this gate keeps a converge quiet, that one stops a hand-run from
# the Nautobot UI.
SLICE_JOBS = {
    "nodes": "Seed Proxmox Node Facts",
    "reservations": "Seed IP Addresses and Reservations",
    "devices": "Seed DCIM Racks and Devices",
    "drives": "Sync Drive Inventory from Proxmox",
}

# Appended AFTER the SSoT list on purpose: a drive is an InventoryItem on its
# node's Device, so "Seed Proxmox Node Facts" has to have created that Device
# first, exactly as Hardware runs after DCIM above.
SSOT_JOBS.append(SLICE_JOBS["drives"])
SEED_JOBS.append(SLICE_JOBS["drives"])


def _populated_slices() -> set:
    """Names of the SLICE_JOBS slices the seed bundle actually carries rows for.

    An unreadable bundle yields none, so every slice-backed job is dropped; the
    jobs that are not slice-backed still run and fail loudly on it.
    """
    root = os.environ.get("NAUTOBOT_ROOT", "/opt/nautobot")
    path = os.environ.get("NAUTOBOT_SEED_FILE", os.path.join(root, "nautobot_seed.json"))
    try:
        with open(path, encoding="utf-8") as handle:
            bundle = json.load(handle)
    except (OSError, ValueError):
        return set()
    return {name for name in SLICE_JOBS if bundle.get(name)}


_populated = _populated_slices()
for _slice, _job in SLICE_JOBS.items():
    if _slice not in _populated and _job in SEED_JOBS:
        SEED_JOBS.remove(_job)
        print("JOB_SKIPPED", _job, "empty-source")

# Celery terminal states (Nautobot JobResult.status mirrors these).
TERMINAL = {"SUCCESS", "FAILURE", "REVOKED"}
TIMEOUT = int(os.environ.get("NAUTOBOT_JOB_TIMEOUT", "300"))

approver = get_user_model().objects.filter(is_superuser=True).order_by("pk").first()


def enqueue(job, job_kwargs):
    """Enqueue a job, tolerating both enqueue_job signatures.

    Nautobot 3.2 takes the job's variables as ONE ``job_kwargs`` mapping and
    rejects a call that omits it: a plain Job (no variables) enqueued the old
    way dies with "`job_kwargs` has to be defined". The pre-3.2 form splatted
    them as real keyword arguments, which 3.2 still accepts but warns about —
    so the SSoT jobs, which pass ``dryrun``, kept working while every plain Job
    silently stopped running. Prefer the new form, fall back to the old.
    """
    try:
        return JobResult.enqueue_job(job, approver, job_kwargs=job_kwargs)
    except TypeError:
        # Older Nautobot: no job_kwargs parameter at all.
        return JobResult.enqueue_job(job, approver, **job_kwargs)


def run_one(name):
    """Enable, enqueue, and poll a single job by display name. Returns True on
    success so the caller can exit non-zero if any seed job failed — Ansible
    must not report the converge green when the database wasn't seeded.

    SSoT DataSource jobs default to a dry run (compute diffs, commit nothing);
    pass ``dryrun=False`` so the additive sync actually persists. Plain Jobs
    (export, onboarding setup) have no such var, so they get an empty mapping —
    empty, NOT absent; see :func:`enqueue`.
    """
    job = Job.objects.filter(name=name).first()
    if job is None:
        print("JOB_SKIPPED", name, "not-registered")
        return False
    if not job.enabled:
        job.enabled = True
        job.save()
    kwargs = {"dryrun": False} if name in SSOT_JOBS else {}
    try:
        result = enqueue(job, kwargs)
    except Exception as exc:  # noqa: BLE001 - enqueue signature is version-sensitive
        print("JOB_ERROR", name, "enqueue:%s" % exc)
        return False
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        result.refresh_from_db()
        status = str(getattr(result, "status", "")).upper()
        if status in TERMINAL:
            print("JOB_DONE", name, status)
            return status == "SUCCESS"
        time.sleep(3)
    print("JOB_TIMEOUT", name)
    return False


if not all([run_one(job_name) for job_name in SEED_JOBS]):
    sys.exit(1)
