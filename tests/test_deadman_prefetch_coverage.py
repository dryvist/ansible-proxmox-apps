"""Every host group the deadman play targets also gets bao_monitoring_secrets.

The service_deadman play's own group set and the openbao_secrets pre-fetch
play's hosts line are two independently hand-maintained lines in two
different files. A group added to one and not the other renders every
OpenBao-backed receiver (Gatus, healthchecks, off-site healthchecks) silently
empty on that group's hosts, with nothing at converge time to say so.
"""

from __future__ import annotations

import re
from pathlib import Path

PLAYBOOKS = Path(__file__).resolve().parent.parent / "playbooks" / "site"


def _hosts_line(text: str, play_name: str) -> set[str]:
    match = re.search(
        rf"- name: {re.escape(play_name)}\n\s+hosts: >-\n((?:\s+[a-z0-9_:]+\n)+)",
        text,
    )
    assert match, f"could not find a hosts: >- block for play {play_name!r}"
    return {group for group in re.split(r"[\s:]+", match.group(1)) if group}


def test_every_deadman_target_group_is_in_the_prefetch_play():
    deadman_text = (PLAYBOOKS / "03-notifications-and-core-apps.yml").read_text()
    deadman_match = re.search(
        r"- name: Deploy keystone SPOF deadman watchdog\n\s+hosts: ([a-z0-9_:]+)\n",
        deadman_text,
    )
    assert deadman_match, "could not find the deadman play's hosts: line"
    deadman_groups = set(deadman_match.group(1).split(":"))

    prefetch_groups = _hosts_line(
        (PLAYBOOKS / "00-load-and-telemetry.yml").read_text(),
        "Pre-fetch resource-domain secrets from OpenBao",
    )

    assert deadman_groups, "no deadman target groups parsed"
    missing = deadman_groups - prefetch_groups
    assert not missing, (
        f"deadman target group(s) {sorted(missing)} are missing from the "
        "openbao_secrets pre-fetch play's hosts: list — bao_monitoring_secrets "
        "will render {} on those hosts"
    )
