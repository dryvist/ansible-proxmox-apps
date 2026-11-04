"""Validate the operator-controlled Squid domain allowlist input."""

from pathlib import Path
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
TEMPLATE = ROOT / "roles" / "agent_sandbox" / "templates" / "agent-allow.py.j2"
DENIED_DOMAINS = ["youtrack.example.invalid", "vikunja.example.invalid"]


def rendered_namespace():
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "agent_sandbox_operator_allowlist_file": "/etc/agent-sandbox-allowlist/operator.txt",
        "agent_sandbox_allowlist_log_file": "/var/log/agent-sandbox/allowed-domains.log",
        "agent_sandbox_proxy_container": "agent-squid",
        "agent_sandbox_denied_domains": DENIED_DOMAINS,
    }
    script = templar.template(trust_as_template(TEMPLATE.read_text(encoding="utf-8")))
    namespace = {"__name__": "agent_allow"}
    exec(compile(script, str(TEMPLATE), "exec"), namespace)
    return namespace


class OperatorAllowlistDomainValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        namespace = rendered_namespace()
        cls.validate_domain = staticmethod(namespace["validate_domain"])
        cls.parse_command = staticmethod(namespace["parse_command"])

    def test_add_refuses_denied_domains_and_their_subdomains(self):
        for command in (
            "add youtrack.example.invalid",
            "add vikunja.example.invalid",
            "add api.youtrack.example.invalid",
            "add deep.edge.vikunja.example.invalid",
            "add *.vikunja.example.invalid",
            "add *.api.youtrack.example.invalid",
            "add VIKUNJA.EXAMPLE.INVALID",
        ):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    self.parse_command(command)

    def test_add_still_accepts_unrelated_domains(self):
        self.assertEqual(self.parse_command("add example.org"), ("add", "example.org"))
        self.assertEqual(
            self.parse_command("add notvikunja.example.invalid"),
            ("add", "notvikunja.example.invalid"),
        )
        self.assertEqual(
            self.parse_command("add shared.example.invalid"),
            ("add", "shared.example.invalid"),
        )

    def test_rm_of_a_denied_domain_stays_available_for_cleanup(self):
        self.assertEqual(
            self.parse_command("rm youtrack.example.invalid"),
            ("rm", "youtrack.example.invalid"),
        )

    def test_accepts_dns_domains_and_one_leading_wildcard(self):
        for domain in ("example.org", "api.example.org"):
            with self.subTest(domain=domain):
                self.assertEqual(self.validate_domain(domain), domain)

    def test_writes_a_leading_wildcard_as_squid_leading_dot(self):
        self.assertEqual(self.validate_domain("*.Example.org"), ".example.org")

    def test_normalizes_dns_names_to_lowercase(self):
        self.assertEqual(self.validate_domain("API.Example.ORG"), "api.example.org")

    def test_accepts_a_domain_at_the_length_limit(self):
        domain = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 61))
        self.assertEqual(len(domain), 253)
        self.assertEqual(self.validate_domain(domain), domain)

    def test_rejects_shell_text_spaces_ips_nested_wildcards_ports_and_long_names(self):
        too_long = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 62))
        for domain in (
            "example.org; touch /tmp/unexpected",
            "example org",
            "192.0.2.1",
            "example.*.org",
            "*.example.*",
            "*.*.example.org",
            "example.org:443",
            too_long,
        ):
            with self.subTest(domain=domain):
                with self.assertRaises(ValueError):
                    self.validate_domain(domain)

    def test_denied_domains_default_builds_names_from_the_environment(self):
        denied = yaml.safe_load(
            (ROLE / "vars/main.yml").read_text(encoding="utf-8")
        )["agent_sandbox_denied_domains"]
        self.assertEqual(len(denied), 2)
        for label in ("youtrack", "vikunja"):
            entry = next(item for item in denied if item.startswith(f"{label}."))
            with self.subTest(label=label):
                self.assertIn("lookup('env', 'PROXMOX_SUBDOMAIN')", entry)
                self.assertIn("mandatory(", entry)

    def test_converge_creates_the_file_only_when_missing(self):
        tasks = yaml.safe_load((ROLE / "tasks/main/deploy.yml").read_text(encoding="utf-8"))
        create = next(
            task
            for task in tasks
            if task["name"] == "Create an empty operator allowlist only when it is absent"
        )
        self.assertEqual(create["ansible.builtin.copy"]["content"], "")
        self.assertIs(create["ansible.builtin.copy"]["force"], False)

        metadata = next(
            task
            for task in tasks
            if task["name"]
            == "Set the operator allowlist ownership and permissions without changing its contents"
        )
        self.assertEqual(metadata["ansible.builtin.file"]["state"], "file")
        self.assertIs(metadata["ansible.builtin.file"]["follow"], False)
        self.assertEqual(
            metadata["when"],
            "not ansible_check_mode or _agent_sandbox_operator_allowlist_file.stat.exists",
        )

    def test_forced_command_key_and_ssh_match_disable_interactive_access(self):
        key_template = (ROLE / "templates/agent-allow-authorized-keys.j2").read_text(
            encoding="utf-8"
        )
        sshd_template = (ROLE / "templates/dispatch-sshd.conf.j2").read_text(
            encoding="utf-8"
        )
        self.assertIn('restrict,command="{{ agent_sandbox_allow_command }}"', key_template)
        self.assertIn("ForceCommand {{ agent_sandbox_allow_command }}", sshd_template)
        self.assertIn("DisableForwarding yes", sshd_template)
        self.assertIn("PermitTTY no", sshd_template)

    def test_sandbox_inventory_enables_the_operator_allowlist_command(self):
        host_vars = yaml.safe_load(
            (ROOT / "inventory/host_vars/ai-sandbox-01.yml").read_text(encoding="utf-8")
        )
        self.assertIs(host_vars["agent_sandbox_allow_access_enabled"], True)
        authorized_keys = host_vars["agent_sandbox_allow_authorized_keys"]
        self.assertGreaterEqual(len(authorized_keys), 1)
        self.assertEqual(len(authorized_keys), len(set(authorized_keys)))
        for key in authorized_keys:
            self.assertTrue(key.startswith("ssh-ed25519 "))


if __name__ == "__main__":
    unittest.main()
