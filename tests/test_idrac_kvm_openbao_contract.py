"""Contract checks for the iDRAC KVM OpenBao credential flow."""

from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
import yaml


ROOT = Path(__file__).resolve().parents[1]
GROUP_VARS = yaml.safe_load((ROOT / "inventory/group_vars/idrac_kvm_group.yml").read_text())
TASKS = yaml.safe_load((ROOT / "roles/idrac_kvm_docker/tasks/main.yml").read_text())
DEFAULTS = yaml.safe_load((ROOT / "roles/idrac_kvm_docker/defaults/main.yml").read_text())


def test_targets_are_disabled_and_values_come_from_prefetch():
    targets = {target["name"]: target for target in GROUP_VARS["idrac_kvm_docker_targets"]}
    assert targets["r410"]["enabled"] is False
    assert targets["r710"]["enabled"] is False
    assert targets["r410"]["host"].endswith("bao_apps_secrets.idrac_kvm_r410_host | default('', true) }}")
    assert targets["r410"]["user"].endswith("bao_apps_secrets.idrac_kvm_r410_user | default('', true) }}")
    assert targets["r410"]["password"].endswith("bao_apps_secrets.idrac_kvm_r410_password | default('', true) }}")
    assert DEFAULTS["idrac_kvm_docker_targets"] == []


def test_missing_prefetch_fields_render_empty_for_disabled_targets():
    templar = Templar(loader=DataLoader())
    templar.available_variables = {}
    targets = []
    for target in GROUP_VARS["idrac_kvm_docker_targets"]:
        rendered = dict(target)
        for field in ("host", "user", "password"):
            rendered[field] = templar.template(trust_as_template(target[field]))
        targets.append(rendered)

    assert all(target["host"] == "" for target in targets)
    assert all(target["user"] == "" for target in targets)
    assert all(target["password"] == "" for target in targets)
    assert not [target for target in targets if target["enabled"]]


def test_preflight_checks_only_enabled_prefetched_values():
    preflight = TASKS[0]
    assert preflight["name"].startswith("Assert iDRAC credentials are available")
    assert preflight["loop"] == "{{ idrac_kvm_docker_targets | selectattr('enabled', 'equalto', true) | list }}"
    assertions = preflight["ansible.builtin.assert"]["that"]
    assert assertions == ["item.host | length > 0", "item.user | length > 0", "item.password | length > 0"]
    assert preflight["no_log"] is True


def test_templates_no_longer_read_process_environment_and_filter_disabled_targets():
    env_template = (ROOT / "roles/idrac_kvm_docker/templates/env.j2").read_text()
    compose_template = (ROOT / "roles/idrac_kvm_docker/templates/docker-compose.yml.j2").read_text()
    role_source = "\n".join(
        path.read_text()
        for path in [ROOT / "roles/idrac_kvm_docker/tasks/main.yml", ROOT / "roles/idrac_kvm_docker/defaults/main.yml"]
    ) + env_template
    assert "lookup('env'" not in role_source
    assert "{{ t.password }}" in env_template
    assert compose_template.count("if t.enabled | bool") == 2
    assert "selectattr('enabled', 'equalto', true) | list" in TASKS[-2]["loop"]
    assert "selectattr('enabled', 'equalto', true) | list" in TASKS[-1]["loop"]
    assert not any("ipmitool" in task.get("name", "").lower() for task in TASKS)


def test_apps_prefetch_includes_console_guest_group():
    groups = yaml.safe_load((ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml").read_text())
    assert "idrac_kvm_group" in groups["openbao_secrets_domain_groups"]["apps"]
