"""Tag paths of the github_runner converge: runner_prune_now,
runner_remove_containers and runner_container_audit.

`ansible-playbook --list-tasks` cannot expand the dynamic include_role in
playbooks/site/04b-github-runners.yml, so the first class runs
tests/runner_tag_paths/fixture_playbook.yml, which has the same tag structure
with debug markers, and asserts which markers each `--tags` run prints. The
second class asserts the real playbook and role carry exactly the fixture's
tags, so the run proves what the real converge selects.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "runner_tag_paths"
FIXTURE_PLAYBOOK = FIXTURE / "fixture_playbook.yml"
REAL_PLAYBOOK = ROOT / "playbooks" / "site" / "04b-github-runners.yml"
REAL_MAIN = ROOT / "roles" / "github_runner" / "tasks" / "main.yml"
FIXTURE_MAIN = FIXTURE / "roles" / "fixture_runner" / "tasks" / "main.yml"


def _markers(tags, *extra):
    out = subprocess.run(
        ["ansible-playbook", str(FIXTURE_PLAYBOOK), "-c", "local", "--tags", tags, *extra],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {line.split('"MARKER:', 1)[1].split('"', 1)[0] for line in out.splitlines() if '"MARKER:' in line}


class TagPaths(unittest.TestCase):
    def test_converge_runs_the_audit_and_never_the_reclaim(self):
        self.assertEqual(_markers("github_runner"), {"CONVERGE_RAN", "AUDIT_RAN", "RECORDED=0"})

    def test_untagged_run_runs_the_audit_and_never_the_reclaim(self):
        self.assertEqual(_markers("all"), {"CONVERGE_RAN", "AUDIT_RAN", "RECORDED=0"})

    def test_converge_plus_runner_prune_now_runs_the_reclaim_too(self):
        self.assertEqual(
            _markers("github_runner,runner_prune_now"),
            {"CONVERGE_RAN", "PRUNE_RAN", "AUDIT_RAN", "RECORDED=0"},
        )

    def test_runner_prune_now_alone_runs_only_the_reclaim(self):
        self.assertEqual(_markers("runner_prune_now"), {"PRUNE_RAN", "RECORDED=0"})

    def test_runner_container_audit_alone_runs_only_the_audit(self):
        self.assertEqual(_markers("runner_container_audit"), {"AUDIT_RAN", "RECORDED=0"})

    def test_runner_remove_containers_alone_runs_only_the_removal(self):
        self.assertEqual(_markers("runner_remove_containers"), {"REMOVE_RAN", "RECORDED=0"})

    def test_removal_plus_audit_runs_both(self):
        self.assertEqual(
            _markers("runner_remove_containers,runner_container_audit"), {"REMOVE_RAN", "AUDIT_RAN", "RECORDED=0"}
        )

    def test_a_failed_audit_run_alone_is_recorded_for_the_site_gate(self):
        self.assertEqual(
            _markers("runner_container_audit", "-e", "fx_audit_fail=true"),
            {"AUDIT_RAN", "RECORDED=1"},
        )


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _import(tasks, file_name):
    matches = [i for i, task in enumerate(tasks) if task.get("ansible.builtin.import_tasks") == file_name]
    assert len(matches) == 1, f"{file_name} must be imported exactly once"
    return matches[0], tasks[matches[0]]


class RealFilesMatchTheFixture(unittest.TestCase):
    def test_playbook_include_and_rescue_carry_the_fixture_tags(self):
        real = _load(REAL_PLAYBOOK)[0]["tasks"][0]
        fixture = _load(FIXTURE_PLAYBOOK)[0]["tasks"][0]
        self.assertEqual(real["block"][0]["name"], "Include github_runner role")
        self.assertNotIn("tags", real, "block tags would reach every role task")
        for part in ("block", "rescue"):
            self.assertEqual(real[part][0]["tags"], fixture[part][0]["tags"], part)
        self.assertEqual(
            real["block"][0]["ansible.builtin.include_role"]["apply"],
            fixture["block"][0]["ansible.builtin.include_role"]["apply"],
        )
        self.assertEqual(
            real["rescue"][0]["ansible.builtin.include_tasks"]["apply"],
            fixture["rescue"][0]["ansible.builtin.include_tasks"]["apply"],
        )

    def test_role_imports_carry_the_fixture_tags_and_order(self):
        real = _load(REAL_MAIN)
        fixture = _load(FIXTURE_MAIN)
        for file_name in ("prune_now.yml", "remove_containers.yml", "container_audit.yml"):
            _, real_task = _import(real, file_name)
            _, fixture_task = _import(fixture, file_name)
            for key in ("tags", "when"):
                self.assertEqual(real_task.get(key), fixture_task.get(key), f"{file_name} {key}")

        prune_at, _ = _import(real, "prune_now.yml")
        audit_at, _ = _import(real, "container_audit.yml")
        disk_at = next(i for i, t in enumerate(real) if t.get("ansible.builtin.include_tasks") == "data_disk.yml")
        self.assertLess(prune_at, disk_at, "the reclaim must run before the data-disk headroom check")
        self.assertEqual(audit_at, len(real) - 1, "the audit is the converge's last task")


AUDIT_PLAYBOOK = FIXTURE / "audit_playbook.yml"
SOCK = '[{"Type":"bind","Source":"/var/run/docker.sock","Destination":"/var/run/docker.sock"}]'
# `docker ps` prints the first field of each line; `docker inspect` prints the lines.
DOCKER_STUB = """#!/bin/sh
if [ "$1" = ps ]; then printf '%s' "$FAKE_INSPECT" | cut -d'|' -f1 | sed 's#^/##'
else printf '%s\\n' "$FAKE_INSPECT"; fi
"""


GOOD_ENV = "ACCESS_TOKEN=never-printed-canary\nLABELS=Linux,X64,review\nNO_DEFAULT_LABELS=true\n"


def _audit(*lines, env_files=None):
    """Run the audit; return (exit code, stdout, audit rows or None). env_files maps suffix -> env file text."""
    with tempfile.TemporaryDirectory() as stub_dir:
        for suffix, text in (env_files or {}).items():
            (Path(stub_dir) / f"runner.env-{suffix}").write_text(text, encoding="utf-8")
        stub = Path(stub_dir) / "docker"
        stub.write_text(DOCKER_STUB, encoding="utf-8")
        stub.chmod(0o755)
        env = dict(os.environ, PATH=f"{stub_dir}:{os.environ['PATH']}", FAKE_INSPECT="\n".join(lines))
        run = subprocess.run(
            [
                *("ansible-playbook", str(AUDIT_PLAYBOOK), "-c", "local", "-e", f"audit_out={stub_dir}/rows.json"),
                *("-e", f"github_runner_env_file={stub_dir}/runner.env"),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        rows_file = Path(stub_dir) / "rows.json"
        rows = json.loads(rows_file.read_text(encoding="utf-8")) if rows_file.exists() else None
    return run.returncode, run.stdout, rows


class ContainerAudit(unittest.TestCase):
    def test_clean_host_passes_and_reports_privileged(self):
        code, out, rows = _audit(
            "/github-runner-1|false|null|[]",
            f'/github-runner-3|false|["994"]|{SOCK}',
            "/github-runner-review-orgx-1|false|null|[]",
            f'/github-runner-heavy-1|false|["994"]|{SOCK}',
            "/buildkit|true|null|[]",
            env_files={"1": GOOD_ENV, "review-orgx-1": GOOD_ENV},
        )
        self.assertEqual(code, 0, out)
        self.assertIn("github-runner-1 LABELS=Linux,X64,review NO_DEFAULT_LABELS=true", out)
        self.assertNotIn("never-printed-canary", out)
        self.assertEqual(
            {r["name"]: r["review"] for r in rows},
            {
                "github-runner-1": True,
                "github-runner-3": False,
                "github-runner-review-orgx-1": True,
                "github-runner-heavy-1": False,
                "buildkit": False,
            },
        )
        self.assertIn("2 review runner container(s)", out)
        self.assertIn("Privileged containers: buildkit", out)

    def test_review_slot_with_the_socket_fails(self):
        code, out, _ = _audit(f"/github-runner-2|false|null|{SOCK}")
        self.assertNotEqual(code, 0)
        self.assertIn("Docker socket or an added group: github-runner-2", out)

    def test_review_pool_with_an_added_group_fails(self):
        code, out, _ = _audit('/github-runner-review-orgx-1|false|["994"]|[]')
        self.assertNotEqual(code, 0)
        self.assertIn("Docker socket or an added group: github-runner-review-orgx-1", out)

    def test_a_seerr_container_fails(self):
        code, out, _ = _audit("/seerr-diag|true|null|[]")
        self.assertNotEqual(code, 0)
        self.assertIn("Containers named seerr-* are on the runner host: seerr-diag", out)

    def test_every_finding_is_reported_when_several_fail(self):
        code, out, _ = _audit("/seerr-diag|true|null|[]", f"/github-runner-1|false|null|{SOCK}")
        self.assertNotEqual(code, 0)
        self.assertIn("Privileged containers: seerr-diag", out)
        self.assertIn("1 review runner container(s)", out)
        self.assertIn("Containers named seerr-* are on the runner host: seerr-diag", out)
        self.assertIn("Docker socket or an added group: github-runner-1", out)

    def test_review_runner_with_self_hosted_or_default_labels_fails(self):
        code, out, _ = _audit(
            "/github-runner-1|false|null|[]",
            "/github-runner-review-orgx-1|false|null|[]",
            "/github-runner-review-orgx-2|false|null|[]",
            env_files={
                "1": "LABELS=self-hosted,Linux,X64,review\nNO_DEFAULT_LABELS=true\n",
                "review-orgx-1": "LABELS=Linux,X64,review\n",
            },
        )
        self.assertNotEqual(code, 0)
        self.assertIn(
            "with self-hosted in LABELS: github-runner-1, github-runner-review-orgx-1, github-runner-review-orgx-2", out
        )
        self.assertIn("github-runner-review-orgx-2 LABELS=missing NO_DEFAULT_LABELS=missing", out)

    def test_no_containers_passes(self):
        code, out, _ = _audit()
        self.assertEqual(code, 0, out)
        self.assertIn("Privileged containers: none", out)


REMOVE_PLAYBOOK = FIXTURE / "remove_playbook.yml"
# Logs each call; inspect prints one row named after the container argument.
REMOVE_STUB = """#!/bin/sh
echo "$*" >> "$CALLS"
case "$1" in
  inspect) printf '/%s|example/image:1|sha256:abc|2026-01-01T00:00:00Z|true|[]\\n' "$4" ;;
  diff) echo 'C /tmp' ;;
esac
"""


def _remove(names_json):
    """Run the removal; return (exit code, stdout, docker calls)."""
    with tempfile.TemporaryDirectory() as stub_dir:
        stub = Path(stub_dir) / "docker"
        stub.write_text(REMOVE_STUB, encoding="utf-8")
        stub.chmod(0o755)
        calls = Path(stub_dir) / "calls"
        env = dict(os.environ, PATH=f"{stub_dir}:{os.environ['PATH']}", CALLS=str(calls))
        extra = f'{{"github_runner_remove_containers": {names_json}}}'
        run = subprocess.run(
            ["ansible-playbook", str(REMOVE_PLAYBOOK), "-c", "local", "-e", extra],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return run.returncode, run.stdout, lines


class ContainerRemoval(unittest.TestCase):
    def test_an_empty_list_is_refused_before_any_docker_call(self):
        code, out, calls = _remove("[]")
        self.assertNotEqual(code, 0)
        self.assertIn("non-empty list", out)
        self.assertEqual(calls, [])

    def test_a_runner_container_name_is_refused_before_any_docker_call(self):
        code, out, calls = _remove('["seerr-diag", "github-runner-review-orgx-1"]')
        self.assertNotEqual(code, 0)
        self.assertIn("No name may start with github-runner", out)
        self.assertEqual(calls, [])

    def test_each_container_is_logged_before_it_is_removed(self):
        code, out, calls = _remove('["seerr-diag"]')
        self.assertEqual(code, 0, out)
        self.assertEqual([c.split()[0] for c in calls], ["inspect", "diff", "rm"])
        self.assertNotIn("Config.Env", calls[0])
        self.assertEqual(calls[2], "rm --force seerr-diag")
        self.assertIn("/seerr-diag|example/image:1|sha256:abc|2026-01-01T00:00:00Z|true|[]", out)
        self.assertIn("C /tmp", out)


if __name__ == "__main__":
    unittest.main()
