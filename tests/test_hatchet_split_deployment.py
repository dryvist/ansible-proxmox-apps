"""Contracts for Hatchet's shared PostgreSQL split deployment."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml
from jinja2 import Template

ROOT = Path(__file__).resolve().parent.parent
GROUPS = ROOT / "inventory/load_tofu/lxc_groups.yml"
DEFAULTS = ROOT / "roles/hatchet_docker/defaults/main.yml"
COMPOSE = ROOT / "roles/hatchet_docker/templates/docker-compose.yml.j2"
TASKS = ROOT / "roles/hatchet_docker/tasks/main.yml"


def test_docker_ai_tag_maps_to_group_and_legacy_group_is_gone():
    source = GROUPS.read_text(encoding="utf-8")
    assert re.search(
        r"\['docker_ai_group'\]\s*if 'docker-ai' in "
        r"\(item\.value\.tags \| default\(\[\]\)\)",
        source,
    )
    assert "'managed-secrets' in (item.value.tags | default([]))" in source
    assert (ROOT / "inventory/group_vars/docker_ai_group.yml").is_file()

    legacy_group = "_".join(("hatchet", "group"))
    assert not (ROOT / "inventory/group_vars" / f"{legacy_group}.yml").exists()
    result = subprocess.run(
        ["git", "grep", "-n", legacy_group],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_compose_uses_dashboard_and_engine_with_pinned_v0114_images():
    compose = COMPOSE.read_text(encoding="utf-8")
    defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))

    assert "hatchet-dashboard:" in compose
    assert "hatchet-engine:" in compose
    assert "hatchet-lite" not in compose
    assert "SERVER_SERVICES: all" in compose
    assert "SERVER_MSGQUEUE_KIND: postgres" in compose
    assert "SERVER_MSGQUEUE_PUBSUB_KIND: postgres" in compose
    assert "SERVER_PAYLOAD_STORE_ENABLE_PAYLOAD_CONSOLIDATION" not in compose

    for image in ("migrate", "admin", "engine", "dashboard"):
        reference = Template(defaults[f"hatchet_docker_{image}_image"]).render()
        assert re.fullmatch(
            rf"ghcr\.io/hatchet-dev/hatchet/hatchet-{image}:v0\.114\.2"
            r"@sha256:[0-9a-f]{64}",
            reference,
        )


def test_migration_and_seed_are_run_once_before_compose_deploy():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    names = [task.get("name") for task in tasks]
    migrate_index = names.index("Migrate Hatchet PostgreSQL schema")
    seed_index = names.index("Seed Hatchet database with shared credentials")
    deploy_index = names.index("Deploy Hatchet and report the engine log tail on failure")

    assert migrate_index < seed_index < deploy_index
    assert tasks[migrate_index]["run_once"] is True
    assert tasks[migrate_index]["no_log"] is True
    assert tasks[seed_index]["run_once"] is True
    assert tasks[seed_index]["no_log"] is True
    assert "certs" in tasks[seed_index]["community.docker.docker_container"]["command"]
    assert "keys" in tasks[seed_index]["community.docker.docker_container"]["command"]

    compose_index = names.index("Render Hatchet docker-compose.yml")
    assert tasks[compose_index]["no_log"] is True
    assert tasks[compose_index]["ansible.builtin.template"]["mode"] == "0600"
