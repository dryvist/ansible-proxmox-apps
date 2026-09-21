#!/usr/bin/env python3
"""Public-repo CI jobs must not default to the self-hosted fleet.

The self-hosted `proxmox` fleet is a shared, limited pool. A job that only
falls back to a hosted runner for fork PRs still queues every same-repo PR on
the fleet -- for a public repo, that queue is the bulk of the backlog even
though nothing in the job needs anything estate-only (an internal DNS name,
OpenBao, the published inventory object, an apt/registry proxy). #2006 fixed
this for the Molecule matrix with one hosted-runner expression; this test
locks that expression onto every job in this file set that still names
`proxmox`, so a job can't regress back to `fork`-only routing unnoticed.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# The #2006 expression (order/whitespace may vary across YAML scalar styles,
# so this checks for the two clauses it must contain, not exact text).
REQUIRED_CLAUSES = (
    "github.event.repository.private == false",
    "github.event.pull_request.head.repo.fork",
)


def _jobs_naming_proxmox():
    for path in sorted(WORKFLOWS.glob("_*.yml")):
        doc = yaml.safe_load(path.read_text())
        for job_id, job in (doc.get("jobs") or {}).items():
            runs_on = job.get("runs-on")
            if isinstance(runs_on, str) and "proxmox" in runs_on:
                yield path.name, job_id, runs_on


class TestHostedRunnerExpression(unittest.TestCase):
    def test_every_job_naming_proxmox_uses_the_hosted_runner_expression(self):
        checked = 0
        for filename, job_id, runs_on in _jobs_naming_proxmox():
            checked += 1
            for clause in REQUIRED_CLAUSES:
                self.assertIn(
                    clause,
                    runs_on,
                    f"{filename}:{job_id} runs-on falls back to the fleet "
                    f"for every same-repo PR (missing {clause!r}); use the "
                    "#2006 hosted-runner expression instead:\n"
                    f"{runs_on}",
                )
        # At least the Molecule jobs must be covered, or this test is
        # silently checking nothing.
        self.assertGreater(checked, 0, "no job named 'proxmox' -- update this test's glob")


if __name__ == "__main__":
    unittest.main()
