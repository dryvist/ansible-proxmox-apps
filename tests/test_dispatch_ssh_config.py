import pathlib
import shutil
import subprocess
import tempfile
import unittest

import jinja2


class DispatcherSSHConfigTest(unittest.TestCase):
    def test_dispatcher_is_restricted_without_changing_other_users(self):
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        template = (
            pathlib.Path(__file__).resolve().parents[1]
            / "roles/agent_sandbox/templates/dispatch-sshd.conf.j2"
        ).read_text()
        rendered = jinja2.Template(template).render(
            agent_sandbox_dispatch_user="agent-dispatch",
            agent_sandbox_dispatch_command="/usr/local/bin/agent-dispatch-ssh",
        )
        with tempfile.TemporaryDirectory() as directory:
            host_key = pathlib.Path(directory) / "host-key"
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)],
                check=True,
            )
            config = pathlib.Path(directory) / "sshd_config"
            config.write_text(f"HostKey {host_key}\n{rendered}")

            def effective(user):
                output = subprocess.check_output(
                    [
                        sshd, "-T", "-f", str(config), "-C",
                        f"user={user},host=example.invalid,addr=127.0.0.1",
                    ],
                    text=True,
                )
                return dict(line.split(" ", 1) for line in output.splitlines())

            dispatch = effective("agent-dispatch")
            for option, expected in {
                "forcecommand": "/usr/local/bin/agent-dispatch-ssh",
                "disableforwarding": "yes",
                "permittty": "no",
                "permituserrc": "no",
                "authenticationmethods": "publickey",
                "passwordauthentication": "no",
                "kbdinteractiveauthentication": "no",
                "authorizedkeysfile": "/etc/ssh/agent-dispatch-keys/agent-dispatch",
            }.items():
                self.assertEqual(dispatch[option], expected, option)
            self.assertEqual(effective("other-user")["forcecommand"], "none")


if __name__ == "__main__":
    unittest.main()
