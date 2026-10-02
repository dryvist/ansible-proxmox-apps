#!/usr/bin/env python3
"""Every group_vars file that reads bao_media_secrets must be a host the
openbao_secrets pre-fetch play actually publishes that fact to.

Which groups *consume* bao_media_secrets (inventory/group_vars/*.yml) and
which groups the pre-fetch play *publishes* it to
(playbooks/site/00-load-and-telemetry.yml) are independently hand-maintained.
A consumer group can fail this two different ways: it can be left out of the
play's own hosts: list entirely, or -- the bug this test was written to catch
-- the play can include the host but the per-host set_fact task can omit
bao_media_secrets from the domains it actually publishes there. Either way
bao_media_secrets renders as {} on that group's hosts, with nothing at
converge time to say so.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GROUP_VARS = REPO_ROOT / "inventory" / "group_vars"
TELEMETRY_PLAYBOOK = REPO_ROOT / "playbooks" / "site" / "00-load-and-telemetry.yml"
PREFETCH_PLAY = "Pre-fetch resource-domain secrets from OpenBao"
PUBLISH_TASK = "Publish each domain's merged secrets to every host in this play"


def _folded_hosts(text: str, play_name: str) -> set:
    match = re.search(
        rf"- name: {re.escape(play_name)}\n\s+hosts: >-\n((?:\s+[a-z0-9_:]+\n)+)",
        text,
    )
    assert match, f"could not find a hosts: >- block for play {play_name!r}"
    return {group for group in re.split(r"[\s:]+", match.group(1)) if group}


def _set_fact_keys(text: str, task_name: str) -> set:
    """Top-level set_fact keys of one named task, e.g. bao_apps_secrets."""
    match = re.search(
        rf"- name: {re.escape(task_name)}\n\s+ansible\.builtin\.set_fact:\n"
        rf"((?:\s+bao_[a-z0-9_]+_secrets:.*\n)+)",
        text,
    )
    assert match, f"could not find a set_fact block for task {task_name!r}"
    return set(re.findall(r"(bao_[a-z0-9_]+_secrets):", match.group(1)))


def _consumer_groups() -> set:
    """Group names whose group_vars file dereferences a field of bao_media_secrets.

    all.yml's own `bao_media_secrets: {}` is the safe default for hosts
    outside every publisher, not a consumer, so it is excluded by the
    attribute-access pattern below (`bao_media_secrets.SOMEKEY`) rather than a
    hardcoded skip.
    """
    groups = set()
    for path in GROUP_VARS.glob("*.yml"):
        if re.search(r"bao_media_secrets\.[A-Za-z_]", path.read_text()):
            groups.add(path.stem)
    return groups


class TestMediaSecretsPublishCoverage(unittest.TestCase):
    def test_every_bao_media_secrets_consumer_is_published_by_the_prefetch_play(self):
        text = TELEMETRY_PLAYBOOK.read_text()
        consumer_groups = _consumer_groups()
        publisher_hosts = _folded_hosts(text, PREFETCH_PLAY)
        published_domains = _set_fact_keys(text, PUBLISH_TASK)

        self.assertTrue(consumer_groups, "no bao_media_secrets consumer group_vars files found")

        missing_hosts = consumer_groups - publisher_hosts
        self.assertFalse(
            missing_hosts,
            f"group_vars consumer group(s) {sorted(missing_hosts)} read bao_media_secrets "
            f"but are not in the {PREFETCH_PLAY!r} play's hosts:",
        )
        self.assertIn(
            "bao_media_secrets",
            published_domains,
            f"consumer group(s) {sorted(consumer_groups)} are hosts of {PREFETCH_PLAY!r}, "
            f"but its {PUBLISH_TASK!r} task does not set bao_media_secrets -- it will "
            "render {} on those hosts",
        )


if __name__ == "__main__":
    unittest.main()
