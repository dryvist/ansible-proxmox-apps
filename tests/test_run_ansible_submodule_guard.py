"""run-ansible.sh syncs a checked-out submodule to its recorded commit before
the dirty-tree guard, so a submodule pointer bump does not refuse the run."""

from pathlib import Path
import subprocess

from test_run_ansible_guards import RunAnsibleSandbox

FILE_PROTOCOL = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}


class RunAnsibleSubmoduleGuard(RunAnsibleSandbox):
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
