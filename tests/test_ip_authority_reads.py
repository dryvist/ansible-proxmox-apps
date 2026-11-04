"""Hold the line on reading guest addresses (docs/IP_AUTHORITY.md).

Configs reach services by name. `container_ip`, and the `ip` field of a guest
in the published inventory, are addresses. The doc names the few owners whose
job is addresses. This test counts every other line, per file, that reads one.

It fails in three cases:

  * A file that is not in READS starts reading an address. Reach the service
    by name instead: `<name>.{{ ingress_domain }}`.
  * A count in READS goes up. Same fix.
  * A count in READS goes down. Lower the number, or delete the entry at zero,
    so the reads you removed cannot quietly come back.

`reserved_ip` is banned everywhere, exempt owners included. The doc explains
why it was removed.

It counts lines, not expressions. Full-line comments are skipped, but a message
that names `container_ip` counts, so stale wording cannot outlive a migration.

Out of scope: rows of the ingress table, whose backend address is Traefik's to
hold, and `ansible_host`, which is how Ansible connects rather than what a
config points at.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("roles", "inventory", "playbooks")
SUFFIXES = {".yml", ".yaml", ".j2", ".py"}

# One line that reads a guest address: the fact load_tofu sets, or the `ip`
# field of a guest entry in the published inventory.
ADDRESS_READ = re.compile(
    r"\bcontainer_ip\b"
    r"|\bvalue\.ip\b"
    r"|\[\s*['\"]ip['\"]\s*\]"
    r"|attribute\s*=\s*['\"](?:value\.)?ip['\"]"
)
RESERVED = re.compile(r"reserved_ip\b")

# Where container_ip comes from. load_tofu turns the published inventory into
# hosts, so reading the inventory is its job.
PRODUCER = ("inventory/load_tofu.yml", "inventory/load_tofu/")
PRODUCER_DEFINITION = ROOT / "inventory/load_tofu/add_lxc_hosts.yml"

# Roles whose job is addresses (docs/IP_AUTHORITY.md, "Where IP-valued
# variables are still legitimate"). No limit.
EXEMPT = {
    "roles/technitium_dns/": "builds the DNS records",
    "roles/nautobot/": "IPAM records addresses by definition",
}

# Every other file that reads an address today, with its exact line count.
READS = {
    # Technitium's own API address and its record inputs. DNS cannot resolve
    # itself, so this is the DNS tier. It is counted anyway, so these shared
    # files cannot grow unrelated reads.
    "inventory/group_vars/technitium_dns_group.yml": 1,
    "playbooks/site/02-dns-and-pipeline.yml": 2,
    # Not covered by a documented exception. Each one either moves to a name,
    # or becomes an exception in docs/IP_AUTHORITY.md before it is exempted.
    "inventory/group_vars/prometheus_group.yml": 6,
    "playbooks/hatchet-killtest.yml": 1,
    "playbooks/sync-cribl-packs.yml": 1,
    "playbooks/tasks/hatchet_killtest_phases.yml": 1,
    "playbooks/tasks/hatchet_killtest_ready_poll.yml": 1,
    "playbooks/tasks/hatchet_killtest_start.yml": 1,
    "roles/agent_sandbox/defaults/main.yml": 2,
    "roles/cribl_stream/defaults/main/44-clickhouse-llm.yml": 1,
    "roles/grafana_stack/defaults/main.yml": 1,
    "roles/haproxy/templates/haproxy.cfg.j2": 6,
    "roles/haproxy/templates/nginx-stream.conf.j2": 3,
    "roles/hatchet_docker/defaults/main.yml": 1,
    "roles/keepalived/defaults/main.yml": 1,
    "roles/keepalived/tasks/main.yml": 1,
    "roles/netmon/defaults/main.yml": 1,
    "roles/openproject_docker/defaults/main.yml": 2,
    "roles/prometheus_stack/defaults/main.yml": 7,
    "roles/service_deadman/defaults/main.yml": 1,
    "roles/traefik/tasks/dashboard_auth.yml": 1,
    "roles/unifi_metrics/defaults/main.yml": 1,
    "roles/wall/defaults/main.yml": 2,
    "roles/zot_registry/tasks/main.yml": 1,
}


def is_comment(line):
    stripped = line.lstrip()
    return stripped.startswith("#") or stripped.startswith("{#")


def scan():
    """Address-reading line counts per file, and every reserved_ip line."""
    counts, reserved = {}, []
    for top in SCAN_ROOTS:
        for path in sorted((ROOT / top).rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            lines = path.read_text(errors="replace").splitlines()
            for number, line in enumerate(lines, 1):
                if is_comment(line):
                    continue
                if RESERVED.search(line):
                    reserved.append("%s:%d" % (rel, number))
                if rel.startswith(PRODUCER) or rel.startswith(tuple(EXEMPT)):
                    continue
                if ADDRESS_READ.search(line):
                    counts[rel] = counts.get(rel, 0) + 1
    return counts, reserved


class IpAuthorityReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts, cls.reserved = scan()

    def test_pattern_matches_the_producer(self):
        # If the fact is renamed, or the pattern stops matching it, every
        # other check here passes on nothing.
        lines = PRODUCER_DEFINITION.read_text().splitlines()
        self.assertTrue(
            any(
                re.match(r"\s*container_ip:", line) and ADDRESS_READ.search(line)
                for line in lines
            ),
            "%s no longer defines container_ip in a form ADDRESS_READ "
            "matches. Update the pattern before trusting this test."
            % PRODUCER_DEFINITION.relative_to(ROOT),
        )

    def test_no_new_address_reads(self):
        for rel, count in sorted(self.counts.items()):
            limit = READS.get(rel, 0)
            with self.subTest(file=rel):
                self.assertLessEqual(
                    count,
                    limit,
                    "%s: address reads %d, allowed %d. Reach the service by "
                    "name: <name>.{{ ingress_domain }}. See "
                    "docs/IP_AUTHORITY.md." % (rel, count, limit),
                )

    def test_limits_only_go_down(self):
        for rel, limit in sorted(READS.items()):
            count = self.counts.get(rel, 0)
            with self.subTest(file=rel):
                self.assertGreaterEqual(
                    count,
                    limit,
                    "%s: address reads %d, listed %d. %s, so the removed "
                    "reads cannot come back."
                    % (
                        rel,
                        count,
                        limit,
                        "Delete its entry in READS"
                        if count == 0
                        else "Lower its entry in READS to %d" % count,
                    ),
                )

    def test_reserved_ip_stays_gone(self):
        self.assertEqual(
            [],
            self.reserved,
            "reserved_ip was removed on purpose; see docs/IP_AUTHORITY.md.",
        )

    def test_exempt_roles_exist(self):
        for prefix in EXEMPT:
            with self.subTest(role=prefix):
                self.assertTrue((ROOT / prefix).is_dir(), "%s does not exist" % prefix)


if __name__ == "__main__":
    unittest.main()
