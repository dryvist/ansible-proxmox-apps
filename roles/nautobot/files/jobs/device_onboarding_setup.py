"""Nautobot Job: wire the Device Onboarding SecretsGroup (issue #138).

Creates (idempotently) the ``device-onboarding`` SecretsGroup and binds two
``environment-variable`` Secret objects — username + password — as the Generic
access-type username/password the nautobot-device-onboarding "Sync Devices From
Network" job (``SSOTSyncDevices``) expects. The credential VALUES never touch
Nautobot's database: the ``environment-variable`` provider resolves them at run
time from the worker's environment (NAUTOBOT_ONBOARD_USERNAME / _PASSWORD in
nautobot.env), so this only wires the indirection.

Scope: SSOTSyncDevices drives SSH-CLI (netmiko) discovery of *network* devices.
Proxmox VE nodes, iDRAC/BMC, and the UniFi controller are not netmiko platforms
— their discovery needs native APIs and is a tracked follow-up. This Job just
makes the SecretsGroup real and logs the seed-derived target set; the actual
sweep is driven by schedule_discovery.py only when real SSH targets exist.

Self-guarding like the other seed jobs: prints markers, never raises.
"""
from __future__ import annotations

import os

from nautobot.apps.jobs import Job, register_jobs

from ssot_common import load_seed

GROUP_NAME = os.environ.get("ONBOARDING_SECRETS_GROUP", "device-onboarding")
USERNAME_ENV = "NAUTOBOT_ONBOARD_USERNAME"
PASSWORD_ENV = "NAUTOBOT_ONBOARD_PASSWORD"


def _onboarding_targets() -> list[dict]:
    """Derive {ip, kind} onboarding targets from the seed bundle."""
    seed = load_seed()
    targets: list[dict] = []
    for node in seed.get("nodes", []):
        if node.get("commissioned", True) and node.get("mgmt_ip"):
            targets.append({"ip": node["mgmt_ip"], "kind": "proxmox-node"})
    for device in seed.get("devices", []):
        if device.get("bmc_ip"):
            targets.append({"ip": device["bmc_ip"], "kind": "bmc"})
    return targets


def _ensure_env_secret(name: str, variable: str):
    """Idempotently ensure an environment-variable-backed Secret object."""
    from nautobot.extras.models import Secret

    secret, _ = Secret.objects.get_or_create(
        name=name,
        defaults={
            "provider": "environment-variable",
            "parameters": {"variable": variable},
        },
    )
    # Reconcile drift on re-run without clobbering unrelated fields.
    changed = False
    if secret.provider != "environment-variable":
        secret.provider = "environment-variable"
        changed = True
    if secret.parameters != {"variable": variable}:
        secret.parameters = {"variable": variable}
        changed = True
    if changed:
        secret.validated_save()
    return secret


def _wire_secrets_group():
    """Ensure the SecretsGroup + Generic username/password associations."""
    from nautobot.extras.choices import (
        SecretsGroupAccessTypeChoices,
        SecretsGroupSecretTypeChoices,
    )
    from nautobot.extras.models import SecretsGroup, SecretsGroupAssociation

    group, _ = SecretsGroup.objects.get_or_create(name=GROUP_NAME)
    pairs = (
        (SecretsGroupSecretTypeChoices.TYPE_USERNAME, "onboarding-username", USERNAME_ENV),
        (SecretsGroupSecretTypeChoices.TYPE_PASSWORD, "onboarding-password", PASSWORD_ENV),
    )
    for secret_type, secret_name, variable in pairs:
        secret = _ensure_env_secret(secret_name, variable)
        SecretsGroupAssociation.objects.update_or_create(
            secrets_group=group,
            access_type=SecretsGroupAccessTypeChoices.TYPE_GENERIC,
            secret_type=secret_type,
            defaults={"secret": secret},
        )
    return group


class ConfigureDeviceOnboarding(Job):
    """Wire the Device Onboarding SecretsGroup and log the target set."""

    class Meta:
        """Job metadata."""

        name = "Configure Device Onboarding Targets"
        description = "Wire the device-onboarding SecretsGroup and log discovery targets."
        has_sensitive_variables = False

    def run(self) -> None:  # noqa: D102 - Nautobot Job entrypoint
        if not os.environ.get(USERNAME_ENV):
            self.logger.warning(
                "%s not set — discovery credentials are not configured; the "
                "SecretsGroup is wired but the sweep stays inert.",
                USERNAME_ENV,
            )
        try:
            group = _wire_secrets_group()
            self.logger.info("Onboarding SecretsGroup wired: %s", group.name)
        except Exception as exc:  # noqa: BLE001 - self-guarding scaffolding
            self.logger.warning("SecretsGroup wiring unavailable: %s", exc)

        targets = _onboarding_targets()
        self.logger.info("Derived %d seed onboarding targets:", len(targets))
        for target in targets:
            self.logger.info("  %s (%s)", target["ip"], target["kind"])
        self.logger.info(
            "SSOTSyncDevices sweeps SSH-CLI network platforms only; Proxmox / "
            "iDRAC / UniFi discovery via native APIs is a tracked follow-up."
        )


register_jobs(ConfigureDeviceOnboarding)
