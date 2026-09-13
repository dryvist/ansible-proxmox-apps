"""Every host group the deadman play targets also gets bao_monitoring_secrets.

The service_deadman play's own group set and the two plays that publish
bao_monitoring_secrets (the combined openbao_secrets pre-fetch play, and the
monitoring-only republish play for the deadman's non-apps hosts) are
independently hand-maintained lines in the same file. A group added to the
deadman play and not to one of the other two renders every OpenBao-backed
receiver (Gatus, healthchecks, off-site healthchecks, Uptime Kuma) silently
empty on that group's hosts, with nothing at converge time to say so.
"""

from __future__ import annotations

import re
from pathlib import Path

PLAYBOOKS = Path(__file__).resolve().parent.parent / "playbooks" / "site"


def _single_line_hosts(text: str, play_name: str) -> set[str]:
    match = re.search(
        rf"- name: {re.escape(play_name)}\n\s+hosts: ([a-z0-9_:]+)\n",
        text,
    )
    assert match, f"could not find a single-line hosts: for play {play_name!r}"
    return set(match.group(1).split(":"))


def _folded_hosts(text: str, play_name: str) -> set[str]:
    match = re.search(
        rf"- name: {re.escape(play_name)}\n\s+hosts: >-\n((?:\s+[a-z0-9_:]+\n)+)",
        text,
    )
    assert match, f"could not find a hosts: >- block for play {play_name!r}"
    return {group for group in re.split(r"[\s:]+", match.group(1)) if group}


def test_every_deadman_target_group_publishes_bao_monitoring_secrets():
    deadman_groups = _single_line_hosts(
        (PLAYBOOKS / "03-notifications-and-core-apps.yml").read_text(),
        "Deploy keystone SPOF deadman watchdog",
    )

    telemetry_text = (PLAYBOOKS / "00-load-and-telemetry.yml").read_text()
    publisher_groups = _folded_hosts(
        telemetry_text, "Pre-fetch resource-domain secrets from OpenBao"
    ) | _single_line_hosts(
        telemetry_text, "Republish the monitoring domain to the deadman watchdog's own hosts"
    )

    assert deadman_groups, "no deadman target groups parsed"
    missing = deadman_groups - publisher_groups
    assert not missing, (
        f"deadman target group(s) {sorted(missing)} are published by neither "
        "the openbao_secrets pre-fetch play nor the monitoring republish play "
        "— bao_monitoring_secrets will render {} on those hosts"
    )
