"""Nautobot Job: configure Device Onboarding targets (issue #138).

Device Onboarding is the live half of the source-of-truth pipeline: it logs into
the real Proxmox VE nodes and iDRAC/BMC (and UniFi gear) to register them. This
Job derives the onboarding target IPs from the seed bundle, ensures a
SecretsGroup wired to the OpenBao-sourced credentials (read from the
environment, never hardcoded), and logs the target list. Live onboarding runs
at cutover, so the Job is self-guarding — it never fails the converge if the
onboarding app is not fully ready.
"""
from __future__ import annotations

import os
from typing import Optional

from nautobot.apps.jobs import Job, register_jobs

from ssot_common import load_seed


def _onboarding_targets() -> list[dict]:
    """Derive {ip, kind} onboarding targets from the seed bundle."""
    seed = load_seed()
    targets: list[dict] = []
    for node in seed["nodes"]:
        if node.get("commissioned", True) and node.get("mgmt_ip"):
            targets.append({"ip": node["mgmt_ip"], "kind": "proxmox-node"})
    for device in seed["devices"]:
        if device.get("bmc_ip"):
            targets.append({"ip": device["bmc_ip"], "kind": "bmc"})
    return targets


def _ensure_secrets_group() -> Optional[str]:
    """Best-effort: ensure a SecretsGroup for onboarding credentials exists.

    Credentials themselves come from OpenBao via the environment; this only wires
    the Nautobot SecretsGroup that the onboarding job references. Returns the
    group name, or None when the surface is unavailable.
    """
    group_name = os.environ.get("ONBOARDING_SECRETS_GROUP", "device-onboarding")
    try:
        from nautobot.extras.models import SecretsGroup

        SecretsGroup.objects.get_or_create(name=group_name)
        return group_name
    except Exception as exc:  # noqa: BLE001 - best-effort scaffolding
        return f"unavailable ({type(exc).__name__})"


class ConfigureDeviceOnboarding(Job):
    """Derive and log the Device Onboarding target set."""

    class Meta:
        """Job metadata."""

        name = "Configure Device Onboarding Targets"
        description = "Derive onboarding targets from the seed and wire the SecretsGroup."
        has_sensitive_variables = False

    def run(self) -> None:  # noqa: D102 - Nautobot Job entrypoint
        targets = _onboarding_targets()
        group = _ensure_secrets_group()
        self.logger.info("Onboarding SecretsGroup: %s", group)
        self.logger.info("Derived %d onboarding targets:", len(targets))
        for target in targets:
            self.logger.info("  %s (%s)", target["ip"], target["kind"])
        if not os.environ.get("ONBOARDING_USERNAME"):
            self.logger.warning(
                "ONBOARDING_USERNAME/ONBOARDING_PASSWORD not set — live onboarding "
                "will be run at cutover with OpenBao-sourced credentials."
            )


register_jobs(ConfigureDeviceOnboarding)
