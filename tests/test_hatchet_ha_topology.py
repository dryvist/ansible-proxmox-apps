"""HA-topology contracts for the Hatchet control plane.

The replica floor and the ingress-pool derivations render through Ansible's
Templar — the engine the role runs under — against fixture ingress shapes
(single-`ip` rows and `backends` pools), so these cases test the committed
expressions rather than a copy of them. Documentation IPs and example.com
names only, mirroring the traefik render fixture.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles/hatchet_docker"
SITE = ROOT / "playbooks/site/03-notifications-and-core-apps.yml"

# Fixture ingress rows shaped like tofu_data.ingress entries: the pool rows
# mirror tests/template_render/verify/traefik.yml's hatchet-engine contract.
UI_SINGLE_IP_ROW = {"name": "hatchet", "ip": "192.0.2.10", "port": 8888}
UI_POOL_ROW = {
    "name": "hatchet",
    "backends": ["hatchet-a.example.com", "hatchet-b.example.com"],
    "port": 8888,
    "health_check": True,
}
ENGINE_POOL_ROW = {
    "name": "hatchet-engine",
    "backends": ["hatchet-engine-a.example.com", "hatchet-engine-b.example.com"],
    "port": 7077,
    "scheme": "h2c",
    "health_check": True,
    "health_check_path": "/ready",
    "health_check_scheme": "http",
    "health_check_port": 18733,
}


def _render(source, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(source))


def _as_bool(value):
    return value is True or str(value).strip().lower() == "true"


def _defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _tasks():
    return yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))


def _render_topology(groups, ingress_rows, min_replicas=None):
    """Render the HA defaults in dependency order against fixture shapes."""
    defaults = _defaults()
    rendered = {
        "hatchet_docker_min_replicas": (
            min_replicas if min_replicas is not None else defaults["hatchet_docker_min_replicas"]
        ),
        "hatchet_docker_control_plane_group": defaults["hatchet_docker_control_plane_group"],
    }
    rendered["hatchet_docker_replicas"] = int(
        _render(defaults["hatchet_docker_replicas"], dict(rendered, groups=groups))
    )
    rendered["hatchet_docker_ingress_routes"] = _render(
        defaults["hatchet_docker_ingress_routes"],
        dict(rendered, hostvars={"localhost": {"tofu_data": {"ingress": ingress_rows}}}),
    )
    for prefix in ("ui", "engine"):
        rendered[f"hatchet_docker_{prefix}_ingress_route"] = _render(
            defaults[f"hatchet_docker_{prefix}_ingress_route"], dict(rendered)
        )
        rendered[f"hatchet_docker_{prefix}_ingress_backends"] = list(
            _render(defaults[f"hatchet_docker_{prefix}_ingress_backends"], dict(rendered))
        )
        rendered[f"hatchet_docker_{prefix}_ingress_ha_ready"] = _as_bool(
            _render(defaults[f"hatchet_docker_{prefix}_ingress_ha_ready"], dict(rendered))
        )
    rendered["hatchet_docker_ingress_ha_ready"] = _as_bool(
        _render(defaults["hatchet_docker_ingress_ha_ready"], dict(rendered))
    )
    return rendered


def test_replica_floor_default_is_two():
    assert _defaults()["hatchet_docker_min_replicas"] == 2


def test_control_plane_group_default_matches_the_site_play_hosts():
    plays = yaml.safe_load(SITE.read_text(encoding="utf-8"))
    hatchet_hosts = [play["hosts"] for play in plays if str(play.get("name", "")).startswith("Configure Hatchet")]
    assert hatchet_hosts == ["docker_ai_group"]
    assert _defaults()["hatchet_docker_control_plane_group"] == "docker_ai_group"


def test_replicas_count_the_control_plane_group():
    pair = _render_topology(groups={"docker_ai_group": ["hatchet-a", "hatchet-b"]}, ingress_rows=[])
    assert pair["hatchet_docker_replicas"] == 2

    solo = _render_topology(groups={"docker_ai_group": ["hatchet-a"]}, ingress_rows=[])
    assert solo["hatchet_docker_replicas"] == 1

    missing = _render_topology(groups={}, ingress_rows=[])
    assert missing["hatchet_docker_replicas"] == 0


def test_replica_floor_assert_runs_before_any_migration_seed_or_deploy():
    tasks = _tasks()
    names = [task["name"] for task in tasks]
    floor = names.index("Require the HA replica floor before deploying the control plane")
    assert tasks[floor]["ansible.builtin.assert"]["quiet"] is True
    assert floor < names.index("Migrate Hatchet PostgreSQL schema")
    assert floor < names.index("Seed Hatchet database with shared credentials")
    assert floor < names.index("Render Hatchet docker-compose.yml")
    assert floor < names.index("Deploy Hatchet and report the engine log tail on failure")


def test_ingress_legs_count_single_ip_and_pool_rows_alike():
    topology = _render_topology(
        groups={"docker_ai_group": ["hatchet-a", "hatchet-b"]},
        ingress_rows=[UI_SINGLE_IP_ROW, ENGINE_POOL_ROW],
    )
    assert topology["hatchet_docker_ui_ingress_backends"] == ["192.0.2.10"]
    assert topology["hatchet_docker_engine_ingress_backends"] == [
        "hatchet-engine-a.example.com",
        "hatchet-engine-b.example.com",
    ]
    assert topology["hatchet_docker_engine_ingress_ha_ready"] is True


def test_ingress_leg_without_health_check_is_not_ha_ready():
    topology = _render_topology(
        groups={"docker_ai_group": ["hatchet-a", "hatchet-b"]},
        ingress_rows=[UI_POOL_ROW, dict(ENGINE_POOL_ROW, health_check=False)],
    )
    assert topology["hatchet_docker_ui_ingress_ha_ready"] is True
    assert topology["hatchet_docker_engine_ingress_ha_ready"] is False
    assert topology["hatchet_docker_ingress_ha_ready"] is False


def test_ingress_leg_with_a_single_backend_is_not_ha_ready():
    topology = _render_topology(
        groups={"docker_ai_group": ["hatchet-a", "hatchet-b"]},
        ingress_rows=[UI_SINGLE_IP_ROW, ENGINE_POOL_ROW],
    )
    assert topology["hatchet_docker_ui_ingress_ha_ready"] is False
    assert topology["hatchet_docker_ingress_ha_ready"] is False


def test_missing_ingress_routes_are_not_ha_ready():
    topology = _render_topology(
        groups={"docker_ai_group": ["hatchet-a", "hatchet-b"]}, ingress_rows=[]
    )
    assert topology["hatchet_docker_ui_ingress_route"] == {}
    assert topology["hatchet_docker_engine_ingress_backends"] == []
    assert topology["hatchet_docker_ingress_ha_ready"] is False


def test_raising_the_min_replica_floor_strictens_the_ingress_legs():
    topology = _render_topology(
        groups={"docker_ai_group": ["hatchet-a", "hatchet-b"]},
        ingress_rows=[UI_POOL_ROW, ENGINE_POOL_ROW],
        min_replicas=3,
    )
    assert topology["hatchet_docker_replicas"] == 2
    assert topology["hatchet_docker_ui_ingress_ha_ready"] is False
    assert topology["hatchet_docker_engine_ingress_ha_ready"] is False


def test_ingress_readiness_report_names_the_routes_and_the_tofu_fix():
    report = next(
        task
        for task in _tasks()
        if task["name"] == "Report Hatchet ingress-pool readiness"
    )
    assert report["run_once"] is True
    assert report["when"] == "not (hatchet_docker_ingress_ha_ready | bool)"
    msg = report["ansible.builtin.debug"]["msg"]
    assert "'hatchet'" in msg
    assert "'hatchet-engine'" in msg
    assert "ingress.tf" in msg
    assert "health_check" in msg
