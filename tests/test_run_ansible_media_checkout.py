"""The runner fetches the reviewed media commit and keeps legacy callers working."""

import json
from pathlib import Path
import subprocess
import unittest

from test_run_ansible_guards import RunAnsibleSandbox

FILE_PROTOCOL = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "protocol.file.allow",
    "GIT_CONFIG_VALUE_0": "always",
}
MEDIA_URL = "https://example.invalid/media-stack.git"
REAL_ROOT = Path(__file__).resolve().parents[1]


class ServarrPinMetadataContract(unittest.TestCase):
    def test_pin_contains_only_a_full_sha_and_has_no_renovate_manager(self):
        pin_text = (REAL_ROOT / "servarr.pin").read_text(encoding="utf-8")
        pin_lines = pin_text.splitlines()
        self.assertEqual(len(pin_lines), 1)
        self.assertRegex(pin_lines[0], r"^[a-f0-9]{40}$")

        renovate = json.loads((REAL_ROOT / "renovate.json").read_text(encoding="utf-8"))
        self.assertFalse(
            any(
                item.get("managerFilePatterns") == [r"^servarr\.pin$"]
                for item in renovate["customManagers"]
            )
        )


class RunAnsiblePinnedMediaCheckout(RunAnsibleSandbox):
    def setUp(self):
        super().setUp()
        self.media_origin = self.work.parent / "media-origin.git"
        self.media_source = self.work.parent / "media-source"
        subprocess.run(
            ["git", "init", "--bare", "-q", str(self.media_origin)], check=True
        )
        subprocess.run(
            ["git", "init", "-q", "--initial-branch=main", str(self.media_source)],
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.media_source,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "test"],
            cwd=self.media_source,
            check=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(self.media_origin)],
            cwd=self.media_source,
            check=True,
        )

        self.media_pin = self._commit_media("pinned")
        self.media_tip = self._commit_media("later")
        subprocess.run(
            ["git", "push", "-q", "origin", "main"], cwd=self.media_source, check=True
        )
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=self.media_origin,
            check=True,
        )

        self._write_pin(self.media_pin)
        self.git_config = {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "protocol.file.allow",
            "GIT_CONFIG_VALUE_0": "always",
            "GIT_CONFIG_KEY_1": f"url.{self.media_origin.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_1": MEDIA_URL,
            "MEDIA_STACK_REPO_URL": MEDIA_URL,
        }

    def _commit_media(self, content):
        playbook = self.media_source / "playbooks" / "site.yml"
        playbook.parent.mkdir(parents=True, exist_ok=True)
        playbook.write_text(f"# {content}\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "playbooks/site.yml"], cwd=self.media_source, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", f"test: {content}"],
            cwd=self.media_source,
            check=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.media_source,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _write_pin(self, pin):
        (self.work / "servarr.pin").write_text(f"{pin}\n", encoding="utf-8")
        self._git("add", "servarr.pin")
        self._git("commit", "-q", "-m", "test: track media pin")
        self._git("push", "-q")

    def _media_head(self):
        return subprocess.run(
            ["git", "-C", str(self.work / "servarr"), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_runner_checks_out_the_sha_in_the_pin_file(self):
        self._write_recap("localhost")
        result = self._run("--limit", "localhost", env_extra=self.git_config)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._media_head(), self.media_pin)
        self.assertNotEqual(self._media_head(), self.media_tip)
        self.assertTrue((self.work / "servarr" / "playbooks" / "site.yml").is_file())

    def test_missing_runtime_url_fails_for_the_media_play(self):
        self._write_recap("localhost")
        env = self.git_config | {"MEDIA_STACK_REPO_URL": ""}
        result = self._run("--limit", "localhost", env_extra=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MEDIA_STACK_REPO_URL must be set", result.stderr)
        self._assert_playbook_not_called()

    def test_non_media_play_does_not_require_runtime_url(self):
        self._write_recap("localhost")
        result = self._run(
            "--limit",
            "localhost",
            env_extra={"MEDIA_STACK_REPO_URL": ""},
            playbook="playbooks/site/01-baseline-infra.yml",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_pin_fails_before_running_ansible(self):
        self._write_pin("not-a-commit")
        result = self._run("--limit", "localhost", env_extra=self.git_config)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "servarr.pin must contain a 40-character lowercase hexadecimal commit SHA",
            result.stderr,
        )
        self._assert_playbook_not_called()

    def test_clone_failure_fails_before_running_ansible(self):
        self._write_recap("localhost")
        env = self.git_config | {
            "GIT_CONFIG_VALUE_1": (self.work.parent / "missing-media-origin.git").as_uri()
        }
        result = self._run("--limit", "localhost", env_extra=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unable to clone the pinned media-stack repository", result.stderr)
        self._assert_playbook_not_called()


class RunAnsibleLegacySubmoduleGuard(RunAnsibleSandbox):
    def _sub_commit(self, sub, text):
        (sub / "f.txt").write_text(text, encoding="utf-8")
        for args in (["add", "f.txt"], ["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", f"test: {text}"]):
            subprocess.run(["git", *args], cwd=sub, check=True, capture_output=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=sub, check=True, capture_output=True, text=True).stdout.strip()

    def _sub_head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.work / "sub", check=True, capture_output=True, text=True).stdout.strip()

    def test_submodule_pointer_bump_converges_on_the_recorded_commit(self):
        sub = Path(self.tmp.name) / "sub"
        subprocess.run(["git", "init", "-q", str(sub)], check=True)
        old = self._sub_commit(sub, "old")
        self._git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "sub")
        self._git("config", "-f", ".gitmodules", "submodule.sub.update", "none")
        self._git("add", ".gitmodules")
        self._git("commit", "-q", "-m", "test: add submodule")
        new = self._sub_commit(sub, "new")
        self._git("-C", "sub", "fetch", "-q")
        self._git("-C", "sub", "checkout", "-q", new)
        self._git("add", "sub")
        self._git("commit", "-q", "-m", "test: bump submodule")
        self._git("push", "-q")
        # The runner's earlier checkout of the submodule is still on the old commit.
        self._git("-C", "sub", "checkout", "-q", old)

        self._write_recap("localhost")
        result = self._run("--limit", "localhost", env_extra=FILE_PROTOCOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._sub_head(), new)

    def test_local_edit_inside_the_submodule_still_refuses(self):
        sub = Path(self.tmp.name) / "sub"
        subprocess.run(["git", "init", "-q", str(sub)], check=True)
        self._sub_commit(sub, "old")
        self._git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "sub")
        self._git("commit", "-q", "-m", "test: add submodule")
        self._git("push", "-q")
        (self.work / "sub" / "f.txt").write_text("locally edited\n", encoding="utf-8")

        result = self._run("--limit", "localhost", env_extra=FILE_PROTOCOL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncommitted changes", result.stderr)
        self._assert_playbook_not_called()
