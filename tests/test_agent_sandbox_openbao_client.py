"""The sandbox dispatcher has a pinned OpenBao CLI outside the SSH PATH."""

from pathlib import Path
import re
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "roles" / "agent_sandbox"
STATE_MODULES = {
    "ansible.builtin.apt",
    "ansible.builtin.copy",
    "ansible.builtin.file",
    "ansible.builtin.group",
    "ansible.builtin.systemd",
    "ansible.builtin.template",
    "ansible.builtin.unarchive",
    "ansible.builtin.user",
}


def task_by_name(tasks, name):
    return next((task for task in tasks if task.get("name") == name), None)


class AgentSandboxOpenBaoClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults = (ROLE / "defaults" / "main.yml").read_text(encoding="utf-8")
        cls.profile = (ROLE / "templates" / "agent-dispatch-profile.sh.j2").read_text(
            encoding="utf-8"
        )
        cls.install = yaml.safe_load(
            (ROLE / "tasks" / "main" / "dispatcher_install.yml").read_text(encoding="utf-8")
        )
        cls.validate_path = ROLE / "tasks" / "main" / "validate_dispatcher.yml"
        cls.validate = (
            yaml.safe_load(cls.validate_path.read_text(encoding="utf-8"))
            if cls.validate_path.exists()
            else []
        )

    def test_archive_checksum_comes_from_the_signed_release_manifest(self):
        manifest = task_by_name(
            self.install, "Stage the OpenBao release checksum manifest on controller"
        )
        signature = task_by_name(
            self.install, "Stage the OpenBao release checksum manifest signature on controller"
        )
        verify = task_by_name(
            self.install, "Verify the OpenBao release checksum manifest signature"
        )
        checksum = task_by_name(
            self.install, "Read the expected SHA256 for OpenBao client archive"
        )
        checksum_assertion = task_by_name(
            self.install, "Assert exactly one OpenBao archive checksum was found"
        )
        checksum_value = task_by_name(self.install, "Set OpenBao archive checksum")
        archive = task_by_name(self.install, "Fetch the pinned OpenBao client to controller")

        self.assertIsNotNone(manifest)
        self.assertIsNotNone(signature)
        self.assertIsNotNone(verify)
        self.assertIsNotNone(checksum)
        self.assertIsNotNone(checksum_assertion)
        self.assertIsNotNone(checksum_value)
        self.assertIsNotNone(archive)
        self.assertIn("ansible.builtin.get_url", manifest)
        for task in (manifest, signature, verify):
            self.assertEqual(task.get("delegate_to"), "localhost")
            self.assertEqual(task.get("connection"), "local")
            self.assertIs(task.get("check_mode"), False)
        self.assertIn("checksums.txt", manifest["ansible.builtin.get_url"]["url"])
        self.assertIn(
            "{{ agent_sandbox_dispatch_bao_version }}",
            manifest["ansible.builtin.get_url"]["url"],
        )
        self.assertLess(self.install.index(manifest), self.install.index(signature))
        self.assertLess(self.install.index(signature), self.install.index(verify))
        self.assertLess(self.install.index(verify), self.install.index(checksum))
        self.assertLess(self.install.index(manifest), self.install.index(archive))
        self.assertLess(self.install.index(checksum), self.install.index(archive))
        self.assertLess(self.install.index(checksum_assertion), self.install.index(archive))
        self.assertLess(self.install.index(checksum_value), self.install.index(archive))
        self.assertIn("gpgv", verify["ansible.builtin.command"]["argv"])
        self.assertEqual(archive.get("delegate_to"), "localhost")
        self.assertIs(archive.get("check_mode"), False)
        self.assertIn(
            "openbao/openbao/releases/download",
            archive["ansible.builtin.get_url"]["url"],
        )
        self.assertEqual(
            checksum_assertion["ansible.builtin.assert"]["that"],
            ["_agent_sandbox_dispatch_bao_checksum_matches | length == 1"],
        )
        checksum_expression = checksum["ansible.builtin.set_fact"][
            "_agent_sandbox_dispatch_bao_checksum_matches"
        ]
        self.assertIn("regex_findall", checksum_expression)
        self.assertIn("openbao_", checksum_expression)
        self.assertIn("_linux_amd64.tar.gz", checksum_expression)
        self.assertEqual(
            checksum_value["ansible.builtin.set_fact"]["agent_sandbox_dispatch_bao_sha256"],
            "{{ _agent_sandbox_dispatch_bao_checksum_matches | first }}",
        )
        self.assertEqual(
            archive["ansible.builtin.get_url"]["checksum"],
            "sha256:{{ agent_sandbox_dispatch_bao_sha256 }}",
        )

        version = re.search(
            r"(?m)^agent_sandbox_dispatch_bao_version: \"([^\"]+)\"$", self.defaults
        )
        static_checksum = re.search(
            r"(?m)^agent_sandbox_dispatch_bao_sha256:\s*[\"']?[0-9a-f]{64}[\"']?\s*$",
            self.defaults,
        )
        self.assertIsNotNone(version)
        self.assertIsNone(static_checksum)
        self.assertIn("# renovate: datasource=github-releases depName=openbao/openbao", self.defaults)

    def test_only_the_bao_binary_is_copied_to_the_absolute_path(self):
        extract = task_by_name(self.install, "Extract the OpenBao client on controller")
        install = task_by_name(self.install, "Install the OpenBao client")

        self.assertIsNotNone(extract)
        self.assertEqual(extract["ansible.builtin.unarchive"].get("include"), ["bao"])
        self.assertIsNotNone(install)
        self.assertEqual(install["ansible.builtin.copy"]["dest"], "{{ agent_sandbox_dispatch_bao_bin }}")
        path = re.search(r"(?m)^agent_sandbox_dispatch_bao_bin: (\S+)$", self.defaults)
        self.assertIsNotNone(path)
        self.assertTrue(Path(path.group(1)).is_absolute())

    def test_controller_stage_directory_is_created_before_extract(self):
        create = task_by_name(
            self.install, "Create the OpenBao client staging directory on controller"
        )
        extract = task_by_name(self.install, "Extract the OpenBao client on controller")

        self.assertIsNotNone(create)
        self.assertLess(self.install.index(create), self.install.index(extract))
        self.assertIs(create.get("check_mode"), False)

    def test_dispatcher_profile_exports_bao_bin(self):
        self.assertRegex(
            self.profile,
            r"(?m)^export BAO_BIN=.*agent_sandbox_dispatch_bao_bin.*$",
        )

    def test_dispatch_account_version_probe_is_asserted_after_install(self):
        probe = task_by_name(self.validate, "Read OpenBao client version as dispatcher account")
        assertion = task_by_name(self.validate, "Require dispatcher account to execute OpenBao client")

        self.assertIsNotNone(probe)
        self.assertEqual(
            probe["ansible.builtin.command"]["argv"],
            ["{{ agent_sandbox_dispatch_bao_bin }}", "version"],
        )
        self.assertEqual(probe.get("become_user"), "{{ agent_sandbox_dispatch_user }}")
        self.assertIn("not ansible_check_mode", probe.get("when", []))
        self.assertIs(probe.get("check_mode"), False)
        self.assertIsNotNone(assertion)
        self.assertIn("_agent_sandbox_bao_version.rc == 0", assertion["ansible.builtin.assert"]["that"])
        self.assertIn("# Read-only version probe; keep it available outside check mode.",
                      self.validate_path.read_text(encoding="utf-8"))

    def test_no_managed_host_state_task_disables_check_mode(self):
        tasks = [*self.install, *self.validate]
        invalid = [
            task.get("name", "unnamed")
            for task in tasks
            if STATE_MODULES.intersection(task)
            and task.get("delegate_to") != "localhost"
            and task.get("check_mode") is False
        ]
        self.assertEqual(invalid, [])


if __name__ == "__main__":
    unittest.main()
