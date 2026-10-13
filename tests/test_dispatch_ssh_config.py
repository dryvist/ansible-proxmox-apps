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
        environment = jinja2.Environment()
        environment.filters["bool"] = bool  # Ansible filter, absent from plain jinja2
        rendered = environment.from_string(template).render(
            agent_sandbox_dispatch_user="agent-dispatch",
            agent_sandbox_dispatch_command="/usr/local/bin/agent-dispatch-ssh-with-alert",
            agent_sandbox_allow_access_enabled=True,
            agent_sandbox_allow_user="agent-allow",
            agent_sandbox_allow_authorized_keys_file="/etc/ssh/agent-dispatch-keys/agent-allow",
            agent_sandbox_allow_command="/usr/local/bin/agent-allow-ssh",
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
                "forcecommand": "/usr/local/bin/agent-dispatch-ssh-with-alert",
                "disableforwarding": "yes",
                "permittty": "yes",
                "permituserrc": "no",
                "authenticationmethods": "publickey",
                "passwordauthentication": "no",
                "kbdinteractiveauthentication": "no",
                "authorizedkeysfile": "/etc/ssh/agent-dispatch-keys/agent-dispatch",
            }.items():
                self.assertEqual(dispatch[option], expected, option)
            allow = effective("agent-allow")
            for option, expected in {
                "forcecommand": "/usr/local/bin/agent-allow-ssh",
                "disableforwarding": "yes",
                "permittty": "no",
                "permituserrc": "no",
                "authenticationmethods": "publickey",
            }.items():
                self.assertEqual(allow[option], expected, option)
            self.assertEqual(effective("other-user")["forcecommand"], "none")


if __name__ == "__main__":
    unittest.main()
