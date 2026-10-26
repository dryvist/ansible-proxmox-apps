"""Contract checks for the proxmox_backup_server role.

Static checks read the role's task files, defaults and inventory. The status
collector template is rendered and run against a stub proxmox-backup-manager
on PATH, which needs bash and GNU date.
"""

import ast
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
TASKS = ROLE / "tasks"
TEMPLATES = ROLE / "templates"

# Any task whose text mentions one of these handles the OpenBao token or the
# PVE token secret, so it must not print its output.
SECRET_MARKERS = (
    "BAO_TOKEN",
    "X-Vault-Token",
    "PBS_TOKEN_SECRET",
    "generate-token",
    "generated_token",
    "token_create",
    "bao_data",
    "bao_merged",
    "bao_read",
    "bao_readback",
)

PARSE_FAILURE_MSG = (
    "token was created but its value could not be parsed; run user delete-token and re-converge"
)


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def flatten(tasks):
    for task in tasks:
        if "block" in task:
            yield from flatten(task["block"])
            yield from flatten(task.get("rescue", []))
        else:
            yield task


def all_tasks():
    for path in sorted(TASKS.glob("*.yml")):
        for task in flatten(load_yaml(path) or []):
            yield path.name, task


class SecretHandling(unittest.TestCase):
    def test_tasks_touching_the_secret_are_no_log(self):
        checked = 0
        for name, task in all_tasks():
            if "ansible.builtin.assert" in task or "ansible.builtin.fail" in task:
                continue
            if any(marker in yaml.safe_dump(task) for marker in SECRET_MARKERS):
                checked += 1
                with self.subTest(file=name, task=task.get("name")):
                    self.assertIs(task.get("no_log"), True)
        self.assertGreater(checked, 5)

    def test_asserts_stay_visible(self):
        for name, task in all_tasks():
            if "ansible.builtin.assert" in task:
                with self.subTest(file=name, task=task.get("name")):
                    self.assertFalse(task.get("no_log"))

    def test_generate_token_is_parsed_without_output_format(self):
        tasks = {t["name"]: t for t in flatten(load_yaml(TASKS / "backup_identity.yml")) if "name" in t}
        argv = tasks["Generate the PVE API token only when it is absent"]["ansible.builtin.command"]["argv"]
        self.assertNotIn("--output-format", argv)

    def test_parse_failure_message_names_the_rotation_and_no_output(self):
        messages = []
        for task in flatten(load_yaml(TASKS / "backup_identity.yml")):
            fail = task.get("ansible.builtin.fail")
            if fail and "could not be parsed" in fail.get("msg", ""):
                messages.append(" ".join(fail["msg"].split()))
        self.assertEqual(messages, [PARSE_FAILURE_MSG])

    def test_existing_token_rotation_hint_is_present(self):
        text = (TASKS / "backup_identity.yml").read_text()
        self.assertIn("proxmox-backup-manager user delete-token pve-backup@pbs pve", text)

    def test_fingerprint_is_parsed_from_cert_info_and_asserted(self):
        text = (TASKS / "backup_identity.yml").read_text()
        self.assertIn(r"^Fingerprint \(sha256\):", text)
        self.assertIn("^([0-9a-f]{2}:){31}[0-9a-f]{2}$", text)

    def test_acl_lookup_reads_the_ugid_column(self):
        text = (TASKS / "backup_identity_acl.yml").read_text()
        self.assertIn("'ugid'", text)
        self.assertNotIn("'authid'", text)


class PublishGate(unittest.TestCase):
    def test_identity_include_requires_publish_and_skips_check_mode(self):
        main = load_yaml(TASKS / "main.yml")
        includes = [t for t in main if t.get("ansible.builtin.include_tasks") == "backup_identity.yml"]
        self.assertEqual(len(includes), 1)
        self.assertIn("proxmox_backup_server_publish_openbao | bool", includes[0]["when"])
        self.assertIn("not ansible_check_mode", includes[0]["when"])

    def test_publish_is_off_by_default_and_on_for_pbs_group(self):
        defaults = load_yaml(ROLE / "defaults" / "main.yml")
        group = load_yaml(REPO / "inventory" / "group_vars" / "pbs_group.yml")
        self.assertIs(defaults["proxmox_backup_server_publish_openbao"], False)
        self.assertIs(group["proxmox_backup_server_publish_openbao"], True)


class DatastoreMode(unittest.TestCase):
    def test_empty_device_routes_to_mount_verification(self):
        includes = {
            t["ansible.builtin.include_tasks"]: t.get("when")
            for t in load_yaml(TASKS / "main.yml")
            if "ansible.builtin.include_tasks" in t
        }
        self.assertEqual(
            includes["datastore_mount.yml"],
            "proxmox_backup_server_datastore_device | default('') | length == 0",
        )
        self.assertIn("length > 0", includes["datastore_disk.yml"])

    def test_mount_assertion_requires_a_separate_mount_at_the_path(self):
        asserts = [
            t["ansible.builtin.assert"]["that"]
            for t in load_yaml(TASKS / "datastore_mount.yml")
            if "ansible.builtin.assert" in t
        ]
        self.assertEqual(len(asserts), 1)
        conditions = " ".join(asserts[0])
        self.assertIn("mount_fields[1] == proxmox_backup_server_datastore_path", conditions)
        self.assertIn("mount_fields[0] != (proxmox_backup_server_root_source.stdout | trim)", conditions)

    def test_datastore_create_read_back_keeps_its_retry(self):
        recheck = [
            t for t in flatten(load_yaml(TASKS / "main.yml"))
            if t.get("name") == "Re-read the datastores after creation"
        ]
        self.assertEqual(len(recheck), 1)
        self.assertIn("until", recheck[0])
        self.assertEqual(recheck[0]["retries"], "{{ proxmox_backup_server_datastore_create_retries }}")


class MaintenanceJobs(unittest.TestCase):
    def test_prune_retention_is_seven_four_six(self):
        defaults = load_yaml(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["proxmox_backup_server_prune_keep_daily"], 7)
        self.assertEqual(defaults["proxmox_backup_server_prune_keep_weekly"], 4)
        self.assertEqual(defaults["proxmox_backup_server_prune_keep_monthly"], 6)

    def test_prune_create_and_update_pass_the_retention(self):
        tasks = {t["name"]: t for t in load_yaml(TASKS / "maintenance_jobs.yml") if "name" in t}
        for name in ("Create the PBS prune job", "Update the PBS prune job when its settings differ"):
            with self.subTest(task=name):
                argv = tasks[name]["ansible.builtin.command"]["argv"]
                for flag, var in (
                    ("--keep-daily", "keep_daily"),
                    ("--keep-weekly", "keep_weekly"),
                    ("--keep-monthly", "keep_monthly"),
                ):
                    self.assertEqual(
                        argv[argv.index(flag) + 1],
                        "{{ proxmox_backup_server_prune_%s | string }}" % var,
                    )


class LxcGroups(unittest.TestCase):
    def test_pbs_tag_derives_pbs_group_for_lxc(self):
        expr = load_yaml(REPO / "inventory" / "load_tofu" / "lxc_groups.yml")["add_lxc_hosts_groups"]
        template = Environment().from_string(expr)

        def groups(tags):
            return ast.literal_eval(template.render(item={"value": {"tags": tags}}).strip())

        self.assertIn("pbs_group", groups(["pbs"]))
        self.assertNotIn("pbs_group", groups(["docker"]))

    def test_classify_tag_derives_classify_gpu_group(self):
        expr = load_yaml(REPO / "inventory" / "load_tofu" / "lxc_groups.yml")["add_lxc_hosts_groups"]
        template = Environment().from_string(expr)

        def groups(tags):
            return ast.literal_eval(template.render(item={"value": {"tags": tags}}).strip())

        self.assertIn("llm_gpu_classify_group", groups(["gpu-passthrough", "llm-gpu-classify"]))
        self.assertNotIn("llm_gpu_classify_group", groups(["gpu-passthrough"]))


class StatusCollector(unittest.TestCase):
    def render(self, status_dir, datastore_path):
        env = Environment(keep_trailing_newline=True)
        env.filters["quote"] = shlex.quote
        return env.from_string((TEMPLATES / "pbs_data_protection_status.sh.j2").read_text()).render(
            proxmox_backup_server_datastore_name="backup",
            proxmox_backup_server_datastore_path=str(datastore_path),
            proxmox_backup_server_status_directory=str(status_dir),
            proxmox_backup_server_verify_job_id="pve-backups-verify",
            proxmox_backup_server_prune_job_id="pve-backups-prune",
        )

    def run_collector(self, task_json, snapshot_time=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            datastore = root / "datastore"
            datastore.mkdir()
            if snapshot_time:
                snapshot = datastore / "ct" / "100" / snapshot_time
                snapshot.mkdir(parents=True)
                (snapshot / "manifest.blob").write_bytes(b"x")

            stub_dir = root / "bin"
            stub_dir.mkdir()
            stub = stub_dir / "proxmox-backup-manager"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                'if [[ "$1" == task && "$2" == list ]]; then\n'
                "cat <<'JSON'\n" + task_json + "\nJSON\n"
                "exit 0\nfi\nexit 1\n"
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
        return [line.split() for line in lines]

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


if __name__ == "__main__":
    unittest.main()
