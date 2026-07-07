"""Shared E2E test fixtures and source matrix.

The syslog source matrix is built from ``constants.syslog_port_map`` in
``inventory/tofu_inventory.json`` — the single source of truth exported by
terraform-proxmox. Nothing here hardcodes ports, indexes, or sourcetypes.
With no inventory (or an inventory predating syslog_port_map) the matrix is
empty and the parametrized tests skip.
"""

import json
from dataclasses import dataclass
from pathlib import Path


def inventory_path():
    """Path to the tofu-generated inventory consumed by all E2E tests."""
    return Path(__file__).resolve().parents[2] / "inventory" / "tofu_inventory.json"


@dataclass(frozen=True)
class SyslogSource:
    """Expected routing contract for one app-facing syslog source family."""

    key: str
    label: str
    standard_port: int
    backend_port: int
    expected_index: str
    expected_sourcetype: str


@dataclass(frozen=True)
class AiSource:
    """Expected routing contract for one AI/LLM log ingest source."""

    key: str
    label: str
    port: int
    expected_index: str
    expected_sourcetype: str


def _load_constants_map(key):
    if not inventory_path().exists():
        return {}
    with open(inventory_path()) as f:
        constants = json.load(f).get("constants", {})
    return constants.get(key, {})


def _load_syslog_port_map():
    return _load_constants_map("syslog_port_map")


SYSLOG_SOURCES = [
    SyslogSource(
        key=key,
        label=key.replace("_", " ").title(),
        standard_port=entry["standard"],
        backend_port=entry["high"],
        expected_index=entry["index"],
        expected_sourcetype=entry["sourcetype"],
    )
    for key, entry in sorted(_load_syslog_port_map().items())
]

SYSLOG_SOURCE_IDS = [source.key for source in SYSLOG_SOURCES]

AI_SOURCES = [
    AiSource(
        key=key,
        label=key.replace("_", " ").title(),
        port=entry["port"],
        expected_index=entry["index"],
        expected_sourcetype=entry["sourcetype"],
    )
    for key, entry in sorted(_load_constants_map("ai_log_routing").items())
]

AI_SOURCE_IDS = [source.key for source in AI_SOURCES]

# rsyslog (omfwd) senders speak RFC3164/5424, so their Cribl Stream inputs are
# syslog-type instead of tcpjson. Mirrors the cribl_stream role's
# cribl_stream_ai_input_types override map — keep the two in sync.
AI_SYSLOG_SOURCE_KEYS = {"homelab_llm", "openbao_audit"}
