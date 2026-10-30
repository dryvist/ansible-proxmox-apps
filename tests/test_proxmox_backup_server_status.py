"""Status collector checks for the proxmox_backup_server role.

The status collector template is rendered and run against a stub
proxmox-backup-manager on PATH, which needs bash and GNU date.
"""

import json
import os
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles" / "proxmox_backup_server"
TEMPLATES = ROLE / "templates"


def load_yaml(path):
    return yaml.safe_load(path.read_text())


class StatusCollector(unittest.TestCase):
    def render(self, status_dir, datastore_path):
        env = Environment(keep_trailing_newline=True)
        env.filters["quote"] = shlex.quote
        defaults = load_yaml(ROLE / "defaults" / "main.yml")
        return env.from_string((TEMPLATES / "pbs_data_protection_status.sh.j2").read_text()).render(
            proxmox_backup_server_datastore_name="backup",
            proxmox_backup_server_datastore_path=str(datastore_path),
            proxmox_backup_server_status_directory=str(status_dir),
            proxmox_backup_server_verify_job_id="pve-backups-verify",
            proxmox_backup_server_prune_job_id="pve-backups-prune",
            proxmox_backup_server_snapshot_max_age_hours=defaults[
                "proxmox_backup_server_snapshot_max_age_hours"
            ],
        )

    def run_collector(self, task_json, snapshot_time=None):
        return self.collect(task_json, snapshot_time)[0]

    def collect(self, task_json, snapshot_time=None, list_rc=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            datastore = root / "datastore"
            datastore.mkdir()
            if snapshot_time:
                snapshot = datastore / "ct" / "100" / snapshot_time
                snapshot.mkdir(parents=True)
                (snapshot / "index.json.blob").write_bytes(b"x")

            stub_dir = root / "bin"
            stub_dir.mkdir()
            stub = stub_dir / "proxmox-backup-manager"
            if list_rc:
                listing = "echo 'task list rejected' >&2\nexit %d\n" % list_rc
            else:
                listing = "cat <<'JSON'\n" + task_json + "\nJSON\nexit 0\n"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "$1" == task && "$2" == list ]]; then\n'
                + listing + "fi\nexit 1\n"
            )
            stub.chmod(0o755)

            status_dir = root / "status"
            script = root / "collector.sh"
            script.write_text(self.render(status_dir, datastore))
            script.chmod(0o755)

            env = dict(os.environ)
            env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(script)], env=env, capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = (status_dir / "pbs.status").read_text().splitlines()
        return [line.split() for line in lines], result.stderr

    def test_zero_snapshots_and_no_tasks_emit_fail_never_pass(self):
        rows = self.run_collector("[]")
        self.assertEqual(len(rows), 4)
        for row in rows:
            with self.subTest(job=row[3]):
                # ts host mechanism job class outcome age_seconds
                self.assertEqual(len(row), 7)
                self.assertEqual(row[2], "pbs")
                self.assertEqual(row[4], "P2")
                self.assertEqual(row[5:], ["fail", "-1"])

    def test_recent_snapshot_and_ok_verify_emit_ok(self):
        now = int(time.time())
        snapshot = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 600))
        upid = "UPID:pbs:00000001:00000002:00000003:verificationjob:pve-backups-verify:root@pam:"
        tasks = json.dumps([{"upid": upid, "status": "OK", "starttime": now - 3700, "endtime": now - 3600}])
        by_job = {row[3]: row[5:] for row in self.run_collector(tasks, snapshot_time=snapshot)}
        self.assertEqual(by_job["snapshot-age"][0], "ok")
        self.assertGreaterEqual(int(by_job["snapshot-age"][1]), 0)
        self.assertEqual(by_job["verify-pve-backups-verify"][0], "ok")
        self.assertEqual(by_job["prune-pve-backups-prune"], ["fail", "-1"])

    def test_snapshot_older_than_max_age_reports_fail(self):
        defaults = load_yaml(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["proxmox_backup_server_snapshot_max_age_hours"], 26)
        snapshot = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 27 * 3600))
        by_job = {
            row[3]: row[5:]
            for row in self.run_collector("[]", snapshot_time=snapshot)
        }
        self.assertEqual(by_job["snapshot-age"][0], "fail")
        self.assertGreater(int(by_job["snapshot-age"][1]), 26 * 3600)

    def test_failed_task_list_is_logged_and_rows_stay_fail(self):
        rows, stderr = self.collect("[]", list_rc=1)
        self.assertIn("task list rejected", stderr)
        self.assertIn("pbs-status-diag: task list failed rc=1", stderr)
        self.assertEqual(len(rows), 4)
        for row in rows:
            with self.subTest(job=row[3]):
                self.assertEqual(row[5:], ["fail", "-1"])

    def test_no_matching_task_logs_the_wanted_id_and_newest_tasks(self):
        now = int(time.time())
        upid = "UPID:pbs:00000001:00000002:00000003:prunejob:other-datastore:root@pam:"
        tasks = json.dumps(
            [
                {
                    "upid": upid,
                    "worker_type": "prunejob",
                    "worker_id": "other-datastore",
                    "status": "OK",
                    "starttime": now - 3700,
                    "endtime": now - 3600,
                }
            ]
        )
        rows, stderr = self.collect(tasks)
        by_job = {row[3]: row[5:] for row in rows}
        self.assertEqual(by_job["prune-pve-backups-prune"], ["fail", "-1"])
        self.assertIn("pbs-status-diag: no task matched job=prune-pve-backups-prune", stderr)
        self.assertIn("want_id=pve-backups-prune", stderr)
        self.assertIn("list_rc=0 total_tasks=1 newest=[prunejob/other-datastore/OK]", stderr)

    def test_prune_row_matches_a_prune_task_named_by_datastore(self):
        now = int(time.time())
        tasks = json.dumps(
            [
                {
                    "worker_type": "prunejob",
                    "worker_id": "backup",
                    "status": "OK",
                    "starttime": now - 21000,
                    "endtime": now - 20900,
                    "upid": "UPID:pbs:00000001:00000001:00000001:6A1B2C3D:prunejob:backup:root@pam:",
                },
                {
                    "worker_type": "backup",
                    "worker_id": "backup:ct/505040",
                    "status": "OK",
                    "starttime": now - 600,
                    "endtime": now - 500,
                    "upid": "UPID:pbs:00000002:00000002:00000002:6A1B2C3E:backup:backup:ct/505040:root@pam:",
                },
            ]
        )
        rows, stderr = self.collect(tasks)
        by_job = {row[3]: row[5:] for row in rows}
        outcome, age_seconds = by_job["prune-pve-backups-prune"]
        self.assertEqual(outcome, "ok")
        self.assertGreaterEqual(int(age_seconds), 20900)
        self.assertLess(int(age_seconds), 20900 + 300)
        self.assertEqual(by_job["garbage-collection-backup"], ["fail", "-1"])
        self.assertEqual(by_job["verify-pve-backups-verify"], ["fail", "-1"])
        self.assertNotIn("no task matched job=prune-pve-backups-prune", stderr)


if __name__ == "__main__":
    unittest.main()
