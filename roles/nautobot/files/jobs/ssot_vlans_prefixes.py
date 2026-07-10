"""SSoT seed job: VLANs and Prefixes (issue #138).

Source of truth: the ``vlans`` (from ``vlan_ids``) and ``prefixes`` (from
``network_cidrs``) arrays of the resolved seed bundle. DiffSyncs them into
Nautobot VLAN + Prefix objects idempotently via the SSoT ``contrib`` framework.

Live-validation notes: Prefix in Nautobot 2.x is scoped by a Namespace
(defaults to ``Global``) and has a required ``type`` (defaults to ``network``);
both defaults are relied on here. VLANs are created global (no VLANGroup), keyed
by ``vid`` — the homelab's vids are unique.
"""
from __future__ import annotations

from typing import Optional

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.ipam.models import VLAN, Prefix
from nautobot_ssot.contrib import NautobotAdapter
from nautobot_ssot.jobs.base import DataSource

from ssot_common import (
    STATUS_ACTIVE,
    AdditiveNautobotModel,
    ensure_location,
    ensure_role,
    load_seed,
)


class VLANModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot VLAN."""

    _model = VLAN
    _modelname = "vlan"
    _identifiers = ("vid",)
    _attributes = ("name", "status__name")

    vid: int
    name: str
    status__name: str


class PrefixModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot Prefix, optionally tied to a VLAN."""

    _model = Prefix
    _modelname = "prefix"
    _identifiers = ("network", "prefix_length")
    _attributes = ("status__name", "vlan__vid", "role__name")

    network: str
    prefix_length: int
    status__name: str
    vlan__vid: Optional[int] = None
    role__name: Optional[str] = None


class VlanPrefixNautobotAdapter(NautobotAdapter):
    """Target adapter: loads existing VLANs/Prefixes from the Nautobot ORM."""

    top_level = ("vlan", "prefix")
    vlan = VLANModel
    prefix = PrefixModel


class VlanPrefixSourceAdapter(Adapter):
    """Source adapter: builds VLAN/Prefix models from the seed bundle."""

    top_level = ("vlan", "prefix")
    vlan = VLANModel
    prefix = PrefixModel

    def __init__(self, *args, job=None, **kwargs):
        """Store the owning Job for logging."""
        super().__init__(*args, **kwargs)
        self.job = job

    def load(self) -> None:
        """Populate VLAN and Prefix models from the seed bundle."""
        seed = load_seed()

        for vlan in seed["vlans"]:
            self.add(
                self.vlan(
                    vid=int(vlan["vid"]),
                    name=str(vlan["name"]),
                    status__name=STATUS_ACTIVE,
                )
            )

        for prefix in seed["prefixes"]:
            network, _, length = str(prefix["prefix"]).partition("/")
            role = prefix.get("role")
            if role:
                ensure_role(role, Prefix)
            vlan_vid = prefix.get("vlan_vid")
            self.add(
                self.prefix(
                    network=network,
                    prefix_length=int(length),
                    status__name=STATUS_ACTIVE,
                    vlan__vid=int(vlan_vid) if vlan_vid is not None else None,
                    role__name=role,
                )
            )


class SeedVlansPrefixes(DataSource):
    """Seed Nautobot VLANs and Prefixes from the hand-maintained network sources."""

    class Meta:
        """Job metadata."""

        name = "Seed VLANs and Prefixes"
        description = "DiffSync VLANs and Prefixes from the resolved seed bundle."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Ensure org scaffolding, then load the seed source adapter."""
        ensure_location()
        self.source_adapter = VlanPrefixSourceAdapter(job=self)
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the Nautobot target adapter."""
        self.target_adapter = VlanPrefixNautobotAdapter(job=self)
        self.target_adapter.load()


register_jobs(SeedVlansPrefixes)
