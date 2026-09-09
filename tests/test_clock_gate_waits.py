#!/usr/bin/env python3
"""The clock gate must wait for synchronization, and must still fail closed.

Certificate authentication fails closed on clock skew, so trust must not be
distributed to a host whose time is wrong -- the gate is real and must stay
fatal.

It was sampled once. The ntp role's restart handler runs earlier in the same
play, and restarting the time daemon clears NTPSynchronized until sync is
re-established, so a single sample taken straight afterwards fails on exactly
the hosts whose clock configuration the run just corrected. Observed in a fleet
converge: three hosts failed this assertion at the same second, immediately
after `RUNNING HANDLER [ntp : Restart chrony]`.

The correction is to retry, never to relax. These assertions fail if the wait
is removed (back to one sample), and equally if the gate is made non-fatal --
because "make the converge green" and "measure at a moment the run did not
poison" are different changes and only one of them is wanted.
"""

import unittest
from pathlib import Path

import yaml

TASKS = (
    Path(__file__).resolve().parent.parent
    / "roles" / "ssh_ca_trust" / "tasks" / "main.yml"
)

GATE = "Assert the host clock is NTP-synchronized"
WAIT = "Wait for the host clock to report NTP synchronization"

# Long enough for a time daemon to re-establish sync after a restart, short
# enough that a genuinely broken clock is reported within one converge.
MIN_WAIT_SECONDS = 60


def _find(tasks, name):
    for task in tasks:
        if task.get("name") == name:
            return task
        for key in ("block", "rescue", "always"):
            if key in task:
                found = _find(task[key], name)
                if found:
                    return found
    return None


class ClockGateWaits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = yaml.safe_load(TASKS.read_text())
        cls.gate = _find(cls.tasks, GATE)
        assert cls.gate is not None, f"{GATE!r} not found in {TASKS}"

    def test_the_gate_waits_rather_than_sampling_once(self):
        wait = _find(self.tasks, WAIT)
        self.assertIsNotNone(wait, "the gate must retry, not sample once")
        self.assertIn("until", wait)
        retries = int(wait["retries"])
        delay = int(wait["delay"])
        self.assertGreaterEqual(
            retries * delay, MIN_WAIT_SECONDS,
            "the wait is too short to survive a time-daemon restart",
        )

    def test_the_gate_still_fails_closed(self):
        rescue = self.gate.get("rescue")
        self.assertTrue(rescue, "a rescue that does not exist cannot report")
        self.assertTrue(
            any("ansible.builtin.fail" in task or "fail" in task for task in rescue),
            "the rescue must re-raise -- a rescue that only logs turns a fatal "
            "clock gate into a warning",
        )

    def test_nothing_in_the_gate_swallows_a_failure(self):
        def walk(node):
            if isinstance(node, list):
                for entry in node:
                    yield from walk(entry)
            elif isinstance(node, dict):
                yield node
                for key in ("block", "rescue", "always"):
                    if key in node:
                        yield from walk(node[key])

        for task in walk(self.gate):
            self.assertNotEqual(task.get("ignore_errors"), True, task.get("name"))
            self.assertNotEqual(task.get("failed_when"), False, task.get("name"))

    def test_the_failure_names_what_it_saw(self):
        # An exhausted `until` fails with an EMPTY message, naming neither the
        # clock nor the value observed. The rescue exists to say both.
        rescue_msg = ""
        for task in self.gate.get("rescue", []):
            body = task.get("ansible.builtin.fail") or {}
            rescue_msg += str(body.get("msg", ""))
        self.assertIn("ssh_ca_trust_ntp.stdout", rescue_msg)
        self.assertIn("inventory_hostname", rescue_msg)


if __name__ == "__main__":
    unittest.main()
