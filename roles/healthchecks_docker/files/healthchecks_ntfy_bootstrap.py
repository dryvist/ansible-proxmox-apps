# Idempotent ntfy notification channel bootstrap for self-hosted Healthchecks.
# Run via `manage.py shell < healthchecks_ntfy_bootstrap.py` (piped through
# `docker exec` by the Ansible task). Prints
# HEALTHCHECKS_NTFY_BOOTSTRAP_CHANGED whenever it mutates state; a re-run
# with no drift prints nothing -- mirrors roles/zammad/files/zammad_bootstrap.rb's
# idempotency contract.
#
# Creates one ntfy Channel per Project (a single-tenant deployment has exactly
# one) and backfills it onto every existing Check via Channel.assign_all_checks().
# Healthchecks has no separate "default channel for new checks" setting: its
# own Check.assign_all_channels() runs on every check creation (front-end
# "Add Check" and the ping-based auto-provisioning API) and assigns every
# channel that already exists in the project at that moment -- so once this
# channel exists, future checks pick it up automatically with no extra config.

import json
import os

from hc.accounts.models import Project
from hc.api.models import Channel

changed = False

url = os.environ["HEALTHCHECKS_NTFY_URL"]
topic = os.environ["HEALTHCHECKS_NTFY_TOPIC"]
token = os.environ.get("HEALTHCHECKS_NTFY_TOKEN", "")
priority = int(os.environ.get("HEALTHCHECKS_NTFY_PRIORITY", "3"))
priority_up = int(os.environ.get("HEALTHCHECKS_NTFY_PRIORITY_UP", "3"))

# Field set matches hc.api.models.NtfyConf exactly -- Channel.ntfy parses
# this JSON with pydantic's strict=True, so an extra or missing key raises.
desired_value = json.dumps(
    {
        "topic": topic,
        "url": url,
        "priority": priority,
        "priority_up": priority_up,
        "token": token,
    }
)

for project in Project.objects.all():
    channel = Channel.objects.filter(project=project, kind="ntfy").first()
    if channel is None:
        channel = Channel.objects.create(project=project, kind="ntfy", value=desired_value)
        changed = True
    elif channel.value != desired_value:
        channel.value = desired_value
        channel.save(update_fields=["value"])
        changed = True

    # Idempotent (M2M .add() is a no-op for already-linked checks); also
    # backfills any check created before this channel existed.
    channel.assign_all_checks()

if changed:
    print("HEALTHCHECKS_NTFY_BOOTSTRAP_CHANGED")
