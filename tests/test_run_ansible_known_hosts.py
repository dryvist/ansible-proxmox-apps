"""run-ansible.sh writes the reviewed host-key pin where the in-process
container transport (paramiko) reads it, and keeps that file loadable."""

from pathlib import Path
import unittest

from test_run_ansible_guards import RunAnsibleSandbox


class RunAnsibleKnownHostsPin(RunAnsibleSandbox):
    # --- host-key pin reaches the in-process transport --------------------

    def _run_with_pin(self, home, pin):
        self._write_recap("a-host")
        return self._run(
            "--limit",
            "a-host",
            env_extra={"HOME": str(home), "SSH_KNOWN_HOSTS": pin},
        )

    def test_pin_is_written_where_the_pct_transport_reads_it(self):
        # proxmox_pct_remote builds a paramiko client in process and reads
        # ~/.ssh/known_hosts directly, so ANSIBLE_SSH_COMMON_ARGS never
        # reaches it. Without this the pin is configured and inert.
        home = self.tmp_path_home()
        result = self._run_with_pin(home, "node ssh-ed25519 AAAAPINNED\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        known = home / ".ssh" / "known_hosts"
        self.assertTrue(known.exists(), "pin was not written to the read path")
        self.assertIn("AAAAPINNED", known.read_text(encoding="utf-8"))
        self.assertEqual(known.stat().st_mode & 0o777, 0o600)

    def test_pin_merges_and_does_not_discard_an_existing_file(self):
        # On a workstation this file belongs to the operator. Overwriting it
        # would silently drop every host they had verified themselves.
        home = self.tmp_path_home()
        known = home / ".ssh" / "known_hosts"
        known.parent.mkdir(parents=True, exist_ok=True)
        known.write_text("theirs ssh-ed25519 AAAAOPERATOR\n", encoding="utf-8")

        self._run_with_pin(home, "node ssh-ed25519 AAAAPINNED\n")
        first = known.read_text(encoding="utf-8")
        self.assertIn("AAAAOPERATOR", first)
        self.assertIn("AAAAPINNED", first)

        # Repeating a run must not keep growing the file.
        self._run_with_pin(home, "node ssh-ed25519 AAAAPINNED\n")
        self.assertEqual(known.read_text(encoding="utf-8"), first)

    def test_marker_lines_never_reach_the_pct_read_path(self):
        # paramiko fails to load a file holding any marker line.
        home = self.tmp_path_home()
        known = home / ".ssh" / "known_hosts"
        known.parent.mkdir(parents=True, exist_ok=True)
        known.write_text("@revoked * ssh-ed25519 AAAAOLD\nme ssh-ed25519 AAAAMINE\n")
        self._run_with_pin(
            home, "node ssh-ed25519 AAAAPIN\n@cert-authority * ssh-ed25519 AAAACA\n"
        )
        text = known.read_text()
        self.assertNotIn("@", text)
        self.assertIn("AAAAMINE", text)
        self.assertIn("AAAAPIN", text)

    def test_pin_replaces_a_stale_key_for_the_same_host(self):
        # paramiko takes the first matching line, so a rotated host key must
        # not lose to the copy an earlier run merged.
        home = self.tmp_path_home()
        known = home / ".ssh" / "known_hosts"
        known.parent.mkdir(parents=True, exist_ok=True)
        known.write_text(
            "192.0.2.9,node ssh-ed25519 AAAAOLD\nother ssh-ed25519 AAAAKEEP\n"
        )
        self._run_with_pin(home, "node,node.example.test ssh-ed25519 AAAANEW\n")
        text = known.read_text()
        self.assertNotIn("AAAAOLD", text)
        self.assertIn("AAAANEW", text)
        self.assertIn("AAAAKEEP", text)

    def tmp_path_home(self):
        home = Path(self.tmp.name) / "fake-home"
        home.mkdir(parents=True, exist_ok=True)
        return home


if __name__ == "__main__":
    unittest.main()
