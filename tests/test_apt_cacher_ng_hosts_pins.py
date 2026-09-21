#!/usr/bin/env python3
"""The apt cache resolves its upstreams through DNS, never a hosts-file pin.

A CDN name pinned in /etc/hosts outlives the node it named; nsswitch prefers
files, so the cache keeps answering 503 for that upstream while DNS already
returns a live address. The role removes such pins on every converge. This
test renders the removal regex the task actually uses and checks it strips a
pin for every upstream host while leaving loopback and self entries alone.
"""

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROLE = Path(__file__).resolve().parent.parent / "roles" / "apt_cacher_ng"
TASK = "Remove /etc/hosts pins for upstream mirror hosts"

KEEP = [
    "127.0.0.1 localhost",
    "::1 localhost ip6-localhost ip6-loopback",
    "10.0.0.1 apt-cacher-ng.example.invalid apt-cacher-ng",
    "# 203.0.113.1 download.proxmox.com",
]


def _task():
    for task in yaml.safe_load((ROLE / "tasks" / "main.yml").read_text()):
        if task.get("name") == TASK:
            return task
    raise AssertionError(f"{TASK!r} not found in {ROLE}")


class AptCacherNgHostsPins(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        env = Environment()
        env.filters["urlsplit"] = lambda url, part: re.match(r"\w+://([^/]+)", url).group(1)
        env.filters["regex_escape"] = re.escape
        cls.hosts = yaml.safe_load(env.from_string(defaults["apt_cacher_ng_dns_only_hosts"]).render(defaults))
        task = _task()["ansible.builtin.lineinfile"]
        assert task["state"] == "absent"
        cls.regexps = [re.compile(env.from_string(task["regexp"]).render(item=h)) for h in cls.hosts]

    def test_every_configured_upstream_is_covered(self):
        self.assertIn("download.proxmox.com", self.hosts)
        self.assertIn("deb.debian.org", self.hosts)
        self.assertEqual(len(self.hosts), len(set(self.hosts)))

    def test_a_pin_for_each_upstream_is_removed(self):
        for host, regexp in zip(self.hosts, self.regexps):
            self.assertRegex(f"203.0.113.1 {host}", regexp)
            self.assertRegex(f"  2001:db8::1\t{host} alias", regexp)

    def test_a_stripped_pin_restarts_the_daemon(self):
        self.assertEqual(_task().get("notify"), "Restart apt-cacher-ng")

    def test_loopback_self_and_comment_lines_are_kept(self):
        for line in KEEP:
            for regexp in self.regexps:
                self.assertNotRegex(line, regexp, f"{line!r} matched {regexp.pattern!r}")
