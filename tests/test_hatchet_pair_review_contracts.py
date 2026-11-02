"""Inventory, database and shared-secret contracts for the Hatchet Docker AI pair.

Expressions render through Ansible's Templar, the engine the loader and the
role use, so these cases test the committed text rather than a copy of it.
"""

from __future__ import annotations

from pathlib import Path

import jinja2.meta
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles/hatchet_docker"
GROUP_VARS = ROOT / "inventory/group_vars/docker_ai_group.yml"
SHARED_KEYS = (
    "SERVER_AUTH_COOKIE_SECRETS",
    "SERVER_ENCRYPTION_MASTER_KEYSET",
    "SERVER_ENCRYPTION_JWT_PRIVATE_KEYSET",
    "SERVER_ENCRYPTION_JWT_PUBLIC_KEYSET",
)
# Distinct values with a '$' so compose escaping is exercised.
SECRETS = {
    "hatchet_docker_server_auth_cookie_secrets": "cookie-a$1 cookie-b",
    "hatchet_docker_server_encryption_master_keyset": "master$keyset",
    "hatchet_docker_server_encryption_jwt_private_keyset": "jwt-private$keyset",
    "hatchet_docker_server_encryption_jwt_public_keyset": "jwt-public$keyset",
}


def _render(source, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(source))


def _tasks():
    return {task["name"]: task for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))}


def test_docker_ai_pair_tags_land_in_managed_secrets_and_docker_ai_groups():
    expression = yaml.safe_load(
        (ROOT / "inventory/load_tofu/lxc_groups.yml").read_text(encoding="utf-8")
    )["add_lxc_hosts_groups"]
    guest = {"tags": ["opentofu", "container", "ai", "ai-orchestration", "docker", "docker-ai", "managed-secrets"]}
    groups = _render(expression, {"item": {"key": "docker-ai", "value": guest}, "tofu_data": {"containers": {"docker-ai": guest}}})
    assert "docker_ai_group" in groups
    assert "managed_secrets_group" in groups


def test_db_host_is_the_writable_apps_primary():
    source = yaml.safe_load(GROUP_VARS.read_text(encoding="utf-8"))["hatchet_docker_db_host"]
    variables = {
        "postgres_apps_primary_host": "apps-primary",
        "postgres_primary_host": "wrong-host",
        "hostvars": {"localhost": {"tofu_data": {"domain": "example.test"}}},
    }
    assert _render(source, variables).strip() == "apps-primary.example.test"


def test_compose_deploy_removes_orphans():
    assert _tasks()["Deploy Hatchet via Docker Compose"]["community.docker.docker_compose_v2"]["remove_orphans"] is True


def test_shared_secrets_are_identical_in_seed_and_both_services():
    source = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    parser = jinja2.Environment()
    parser.filters.update(to_json=str, mandatory=str)  # names only; Templar renders below
    names = jinja2.meta.find_undeclared_variables(parser.parse(source))
    variables = {name: "x" for name in names} | SECRETS | {"hatchet_docker_worker_enabled": False}
    services = yaml.safe_load(_render(source, variables))["services"]
    seed_env = _tasks()["Seed Hatchet database with shared credentials"]["community.docker.docker_container"]["env"]

    for key in SHARED_KEYS:
        seed = _render(seed_env[key], variables)
        # Compose turns '$$' back into '$' at interpolation time.
        dashboard = services["hatchet-dashboard"]["environment"][key].replace("$$", "$")
        engine = services["hatchet-engine"]["environment"][key].replace("$$", "$")
        assert seed == dashboard == engine, key
    assert len({_render(seed_env[key], variables) for key in SHARED_KEYS}) == len(SHARED_KEYS)
