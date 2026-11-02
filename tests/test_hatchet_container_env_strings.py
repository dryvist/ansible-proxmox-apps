"""community.docker.docker_container rejects non-string env values; every Hatchet task env renders strings."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles/hatchet_docker"
TASK_FILES = sorted((ROLE / "tasks").glob("*.yml"))


def _container_envs():
    for path in TASK_FILES:
        for task in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            module = task.get("community.docker.docker_container")
            if module and "env" in module:
                yield f"{path.name}:{task['name']}", module["env"]


def _variables():
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    # Integer ports, as the inventory constants supply them.
    port_names = [name for name in defaults if name.endswith("_port")]
    return defaults | {name: 8000 + index for index, name in enumerate(port_names)} | {
        name: "x" for name in (
            "hatchet_docker_database_url", "hatchet_docker_server_url", "hatchet_docker_fqdn",
            "hatchet_docker_engine_broadcast_address", "hatchet_docker_server_auth_cookie_secrets",
            "hatchet_docker_server_encryption_master_keyset",
            "hatchet_docker_server_encryption_jwt_private_keyset",
            "hatchet_docker_server_encryption_jwt_public_keyset", "hatchet_docker_admin_email",
            "hatchet_docker_admin_password", "hatchet_docker_admin_name",
        )
    }


ENVS = list(_container_envs())


def test_role_has_container_envs_to_check():
    assert ENVS


@pytest.mark.parametrize(("task", "env"), ENVS, ids=[task for task, _ in ENVS])
def test_every_container_env_value_renders_a_string(task, env):
    templar = Templar(loader=DataLoader())
    templar.available_variables = _variables()
    for key, value in env.items():
        rendered = templar.template(trust_as_template(value)) if isinstance(value, str) else value
        assert isinstance(rendered, str), f"{task} {key} renders {type(rendered).__name__}"


def _container_tasks():
    for path in TASK_FILES:
        for task in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            module = task.get("community.docker.docker_container")
            if module:
                yield f"{path.name}:{task['name']}", module


def test_one_shot_containers_clean_up_without_auto_remove():
    one_shots = [(name, module) for name, module in _container_tasks() if module.get("detach") is False]
    assert one_shots
    for name, module in one_shots:
        # auto_remove deletes the container before the module can read its output and exit code.
        assert not module.get("auto_remove", False), name
        assert module.get("cleanup") is True, name
