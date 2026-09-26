"""The SSH host-certificate signing role, under the same CA as the user roles.

`openbao_ssh_roles` (05-ssh-ca-engine.yml) carries a `host-cert` entry that
must render a HOST-only role body in the reconcile task
(roles/openbao/tasks/init/07-ssh-ca-engine.yml): `allow_host_certificates`,
`allowed_domains`, `allow_subdomains`, `allow_bare_domains`, `ttl`, `max_ttl`
-- and never `allow_user_certificates`, since a role that can sign both
would let anything holding the sign endpoint mint a host cert for one of
`allowed_users` too.

These render the REAL body expression out of the task file, never a
reimplementation of the branch -- see test_openbao_terrakube_api_update_guard.py
for why that matters (retyping a template performs its own escaping and can
pass while the real expression fails).
"""

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
TASK_REL = "roles/openbao/tasks/init/07-ssh-ca-engine.yml"
TASK_NAME = "Reconcile the SSH signing roles"
DEFAULTS = ROOT / "roles/openbao/defaults/main"


def _read_defaults(filename: str) -> dict:
    return yaml.safe_load((DEFAULTS / filename).read_text(encoding="utf-8"))


def _task():
    for task in yaml.safe_load((ROOT / TASK_REL).read_text(encoding="utf-8")):
        if task.get("name") == TASK_NAME:
            return task
    raise AssertionError(f"task {TASK_NAME!r} not found in {TASK_REL}")


def _render_body(role_entry, source_cidrs=""):
    """Render the task's own `body` expression for one openbao_ssh_roles entry.

    `item` is the (role_entry, check_result) tuple the real `loop: ... | zip(...)`
    produces; the check result is never read by `body`, so an empty dict
    stands in for it.
    """
    task = _task()
    body_expr = task["ansible.builtin.uri"]["body"]
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "item": (role_entry, {}),
        "openbao_ssh_source_address_cidrs": source_cidrs,
    }
    return templar.template(trust_as_template(body_expr))


LIVE_SSH_ROLES = _read_defaults("05-ssh-ca-engine.yml")["openbao_ssh_roles"]


def _live_entry(name):
    for entry in LIVE_SSH_ROLES:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"{name!r} not in the live openbao_ssh_roles list")


def test_live_host_cert_entry_has_no_user_cert_fields():
    entry = _live_entry("host-cert")
    assert entry["cert_type"] == "host"
    assert entry["allow_host_certificates"] is True
    assert entry["allow_subdomains"] is True
    assert entry["allow_bare_domains"] is False
    assert entry["ttl"] == 7776000
    assert entry["max_ttl"] == 7776000
    assert "principal" not in entry
    assert "extensions" not in entry


def test_host_role_body_is_host_only():
    body = _render_body(
        {
            "name": "host-cert",
            "cert_type": "host",
            "allow_host_certificates": True,
            "allowed_domains": "example.com",
            "allow_subdomains": True,
            "allow_bare_domains": False,
            "ttl": 7776000,
            "max_ttl": 7776000,
        }
    )

    assert body["allow_host_certificates"] is True
    assert body["allowed_domains"] == "example.com"
    assert body["allow_subdomains"] is True
    assert body["allow_bare_domains"] is False
    assert body["ttl"] == 7776000
    assert body["max_ttl"] == 7776000

    # The one thing that must never happen: a role that can sign both shapes.
    assert "allow_user_certificates" not in body
    assert "allowed_users" not in body
    assert "default_user" not in body


def test_user_role_body_is_unchanged():
    # Same shape the pre-existing roles rendered before this change: no
    # cert_type field at all, defaulting to 'user' in the task.
    body = _render_body(
        {
            "name": "automation-ansible",
            "principal": "ansible",
            "ttl": 7200,
            "extensions": {},
        }
    )

    assert body["allow_user_certificates"] is True
    assert body["allowed_users"] == "ansible"
    assert body["default_user"] == "ansible"
    assert body["ttl"] == 7200
    assert body["max_ttl"] == 7200
    assert "allow_host_certificates" not in body
    assert "allowed_domains" not in body


def test_explicit_user_cert_type_renders_the_same_as_the_default():
    implicit = _render_body({"name": "x", "principal": "p", "ttl": 60, "extensions": {}})
    explicit = _render_body(
        {"name": "x", "cert_type": "user", "principal": "p", "ttl": 60, "extensions": {}}
    )
    assert implicit == explicit


def test_source_address_restriction_still_applies_to_user_roles():
    body = _render_body(
        {"name": "automation-ansible", "principal": "ansible", "ttl": 7200, "extensions": {}},
        source_cidrs="192.0.2.0/24",
    )
    assert body["default_critical_options"] == {"source-address": "192.0.2.0/24"}


def test_ssh_sign_policy_is_derived_for_the_host_cert_role():
    """openbao_ssh_sign_policies (07a) must pick up host-cert automatically --
    no separate declaration, per the ssh-sign-<role> derivation rule."""
    derived_expr = _read_defaults("07a-derived-rollups-and-ttls.yml")[
        "openbao_ssh_sign_policies"
    ]
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "openbao_ssh_roles": LIVE_SSH_ROLES,
        "openbao_ssh_engine_enabled": True,
    }
    policies = templar.template(trust_as_template(derived_expr))

    names = [p["name"] for p in policies]
    assert "ssh-sign-host-cert" in names
    host_policy = next(p for p in policies if p["name"] == "ssh-sign-host-cert")
    assert host_policy["ssh_role"] == "host-cert"
    assert host_policy["template"] == "ssh-sign-policy.hcl.j2"


def test_ssh_sign_host_cert_is_attached_to_both_unattended_identities():
    """ssh-sign-host-cert must be on ansible-converge AND automation-semaphore
    -- issuance runs unattended in Semaphore, and ansible-converge is the
    shared consumer inventory every Semaphore run attaches too."""
    approles = _read_defaults("07b-base-approles.yml")["openbao_base_approles_core"]

    def _find(name_needle):
        for role in approles:
            if name_needle in role["name"]:
                return role
        raise AssertionError(f"no AppRole entry with {name_needle!r} in its name")

    converge_role = _find("openbao_ansible_converge_approle_name")
    semaphore_role = _find("openbao_semaphore_approle_name")

    templar = Templar(loader=DataLoader())

    templar.available_variables = {
        "openbao_ansible_converge_policy_name": "ansible-converge",
        "openbao_config_write_policy_name": "config-write",
        "openbao_ssh_engine_enabled": True,
    }
    converge_policies = templar.template(trust_as_template(converge_role["token_policies"]))
    assert "ssh-sign-host-cert" in converge_policies

    templar.available_variables = {
        "openbao_ansible_converge_policy_name": "ansible-converge",
        "openbao_semaphore_policy_name": "semaphore",
        "openbao_reconcile_policy_name": "reconcile",
        "openbao_ssh_engine_enabled": True,
    }
    semaphore_policies = templar.template(trust_as_template(semaphore_role["token_policies"]))
    assert "ssh-sign-host-cert" in semaphore_policies


def test_ssh_sign_host_cert_absent_when_engine_disabled():
    """The existing ssh_engine_enabled kill switch must still cover the new
    leaf -- disabling the engine strips every ssh-sign-* grant, host included."""
    approles = _read_defaults("07b-base-approles.yml")["openbao_base_approles_core"]
    converge_role = next(
        r for r in approles if "openbao_ansible_converge_approle_name" in r["name"]
    )

    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "openbao_ansible_converge_policy_name": "ansible-converge",
        "openbao_config_write_policy_name": "config-write",
        "openbao_ssh_engine_enabled": False,
    }
    policies = templar.template(trust_as_template(converge_role["token_policies"]))
    assert "ssh-sign-host-cert" not in policies
    assert "ssh-sign-automation-ansible" not in policies
