"""SSoT seed job: IP addresses and reservations (issue #138).

Source of truth: the ``reservations`` array of the seed bundle (from
``tofu-unifi`` ``fixed-ips.json``). DiffSyncs each reservation into a Nautobot
IPAddress (host + dns_name), idempotently.

Live-validation notes: Nautobot 2.x requires each IPAddress to fall inside an
existing parent Prefix in its Namespace (default ``Global``). Run the VLANs and
Prefixes seed job first so those parents exist; reservations are created with a
/32 mask under the containing prefix. IP-to-interface binding is deferred to
Device Onboarding.
"""
from __future__ import annotations

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.ipam.models import IPAddress
from nautobot_ssot.contrib import NautobotAdapter
from nautobot_ssot.jobs.base import DataSource

from ssot_common import (
    STATUS_ACTIVE,
    AdditiveNautobotModel,
    ensure_location,
    load_seed,
)


class IPAddressModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot IPAddress."""

    _model = IPAddress
    _modelname = "ip_address"
    _identifiers = ("host",)
    _attributes = ("mask_length", "status__name", "dns_name")

    host: str
    mask_length: int
    status__name: str
    dns_name: str = ""


class IPAddressNautobotAdapter(NautobotAdapter):
    """Target adapter: loads existing IP addresses from the Nautobot ORM."""

    top_level = ("ip_address",)
    ip_address = IPAddressModel


class IPAddressSourceAdapter(Adapter):
    """Source adapter: builds IPAddress models from the seed reservations."""

    top_level = ("ip_address",)
    ip_address = IPAddressModel

    def __init__(self, *args, job=None, **kwargs):
        """Store the owning Job for logging."""
        super().__init__(*args, **kwargs)
        self.job = job

    def load(self) -> None:
        """Populate IPAddress models from the seed reservations."""
        seed = load_seed()
        for reservation in seed["reservations"]:
            address = reservation.get("address")
            if not address:
                continue
            host = str(address).split("/", 1)[0]
            self.add(
                self.ip_address(
                    host=host,
                    mask_length=32,
                    status__name=STATUS_ACTIVE,
                    dns_name=str(reservation.get("dns_name") or ""),
                )
            )


class SeedIPAddresses(DataSource):
    """Seed Nautobot IP addresses from the hand-maintained reservations."""

    class Meta:
        """Job metadata."""

        name = "Seed IP Addresses and Reservations"
        description = "DiffSync IP address reservations from the resolved seed bundle."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Ensure org scaffolding, then load the seed source adapter."""
        ensure_location()
        self.source_adapter = IPAddressSourceAdapter(job=self)
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the Nautobot target adapter."""
        self.target_adapter = IPAddressNautobotAdapter(job=self)
        self.target_adapter.load()


register_jobs(SeedIPAddresses)
