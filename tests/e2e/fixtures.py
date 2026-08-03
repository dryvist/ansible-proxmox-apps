"""Shared E2E test fixtures and source matrix.

The syslog source matrix is built from ``constants.syslog_port_map`` in the
resolved OpenTofu inventory — the single source of truth published by
tofu-proxmox. Nothing here hardcodes ports, indexes, or sourcetypes.
With no inventory (or an inventory predating syslog_port_map) the matrix is
empty and the parametrized tests skip.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path


def inventory_path():
    """Path to the OpenTofu inventory consumed by all E2E tests.

    Reads TOFU_INVENTORY_PATH, the same tier-1 pin `inventory_resolve` uses,
    so tests and converges agree on where inventory comes from. There is no
    on-disk default: the published object is the only live source, and a path
    guessed relative to the repo cannot know whether it is current.

    Unset returns a path that cannot exist, so callers skip via their existing
    ``.exists()`` check. Path("") would be Path(".") — a directory that exists
    and then fails on open.
    """
    return Path(os.environ.get("TOFU_INVENTORY_PATH") or "/nonexistent/TOFU_INVENTORY_PATH-unset")


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
