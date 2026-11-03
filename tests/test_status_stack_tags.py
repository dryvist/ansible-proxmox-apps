"""Keep status_stack component tags isolated while preserving full runs."""

from __future__ import annotations

import ast
import base64
import subprocess
from pathlib import Path

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/site/04-secrets-and-collab-apps.yml"
ROLE_LIST_TASKS_PLAYBOOK = ROOT / "tests/status_stack_tags/list_role_tasks.yml"
STATUS_INVENTORY = ROOT / "tests/status_stack_tags/inventory.yml"
ROLE_TASKS = ROOT / "roles/status_stack/tasks/main.yml"
COMPOSE_TEMPLATE = ROOT / "roles/status_stack/templates/docker-compose.yml.j2"
AUTOKUMA_TASKS = ROOT / "roles/status_stack/tasks/autokuma_static_monitors.yml"
ROLE_META = ROOT / "roles/status_stack/meta/main.yml"
ROLE_VARS = ROOT / "roles/status_stack/vars/main.yml"
ROLE_HANDLERS = ROOT / "roles/status_stack/handlers/main.yml"
BROAD_TAGS = {"status", "dashboard", "observability", "collaboration"}
COMPONENT_TAGS = {"gatus", "uptime_kuma", "autokuma"}


def _tags(value):
    return {value} if isinstance(value, str) else set(value or [])


def _walk(tasks, inherited_tags=frozenset()):
    for task in tasks or []:
        tags = inherited_tags | _tags(task.get("tags"))
        yield task, tags
        for key in ("block", "rescue", "always"):
            yield from _walk(task.get(key), tags)


def _read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def _named(tasks):
    return {
        task.get("name"): (task, tags)
        for task, tags in tasks
        if task.get("name")
    }


def _selected_services(expression, run_tags):
    env = jinja2.Environment()
    env.filters["intersect"] = lambda sequence, values: [
        item for item in sequence if item in values
    ]
    rendered = env.from_string(expression).render(ansible_run_tags=run_tags, omit="OMIT")
    return None if rendered == "OMIT" else ast.literal_eval(rendered)


def test_gatus_tag_reaches_only_gatus_component_tasks():
    plays = _read(PLAYBOOK)
    play = next(
        play for play in plays
        if play.get("name") == "Configure status stack (Gatus + Uptime Kuma)"
    )
    assert not (_tags(play.get("tags")) & COMPONENT_TAGS)

    play_tasks = _named(list(_walk(play.get("tasks"))))
    gather_task, _ = play_tasks["Gather facts"]
    assert COMPONENT_TAGS <= _tags(gather_task.get("tags"))
    assert _tags(
        gather_task["ansible.builtin.include_tasks"].get("apply", {}).get("tags")
    ) == COMPONENT_TAGS | BROAD_TAGS

    rescue_task, _ = play_tasks["Record isolated failure and continue"]
    assert COMPONENT_TAGS <= _tags(rescue_task.get("tags"))
    assert _tags(
        rescue_task["ansible.builtin.include_tasks"].get("apply", {}).get("tags")
    ) == COMPONENT_TAGS | BROAD_TAGS

    include_task, _ = play_tasks["Include status_stack role"]
    assert COMPONENT_TAGS <= _tags(include_task.get("tags"))
    include_role = include_task["ansible.builtin.include_role"]
    assert "gatus" not in _tags(include_role.get("apply", {}).get("tags"))
    assert BROAD_TAGS <= _tags(include_role.get("apply", {}).get("tags"))

    role_tasks = _named(list(_walk(_read(ROLE_TASKS))))
    auto_tasks = _named(list(_walk(_read(AUTOKUMA_TASKS))))
    gatus_tasks = {name for name, (_, tags) in role_tasks.items() if "gatus" in tags}
    assert gatus_tasks == {
        "Build the shared service catalog",
        "Assert dashboard catalog is available for Gatus",
        "Ensure status stack data directory exists",
        "Ensure Gatus data directories exist",
        "Read any persisted Uptime Kuma admin password",
        "Read the persisted Uptime Kuma admin password",
        "Require a persisted Uptime Kuma password for a Gatus-only run",
        "Resolve the persisted Uptime Kuma password for Gatus",
        "Render Gatus configuration",
        "Render status stack docker-compose",
        "Deploy status stack via docker compose",
        "Flush handlers so health checks see the new containers",
        "Wait for Gatus HTTP port",
        "Verify Gatus answers /",
    }
    assert all(
        "gatus" not in tags
        for name, (_, tags) in role_tasks.items()
        if name in {
            "Ensure Uptime Kuma data directory exists",
            "Seed Uptime Kuma's admin password in OpenBao",
            "Resolve Uptime Kuma's admin password from OpenBao",
            "Require the persisted Uptime Kuma password to match OpenBao",
            "Persist Uptime Kuma's admin password",
            "Create Uptime Kuma initial admin",
        }
    )
    assert all("gatus" not in tags for name, (_, tags) in role_tasks.items() if "AutoKuma" in name)
    compose_render, compose_tags = role_tasks["Render status stack docker-compose"]
    assert "gatus" in compose_tags
    assert all("gatus" not in tags for _, tags in auto_tasks.values())

    catalog_include = role_tasks["Build the shared service catalog"][0]["ansible.builtin.include_role"]
    assert _tags(catalog_include.get("apply", {}).get("tags")) == {
        "gatus"
    } | BROAD_TAGS
    auto_include, auto_tags = role_tasks["Render and ship the AutoKuma static-monitor set"]
    assert "gatus" not in auto_tags
    assert "autokuma" in _tags(auto_include.get("tags"))
    assert _tags(
        auto_include["ansible.builtin.include_tasks"].get("apply", {}).get("tags")
    ) == {"autokuma"} | BROAD_TAGS

    seed_task, seed_tags = role_tasks[
        "Seed the Uptime Kuma admin password through the shared seed_generated task"
    ]
    assert "gatus" not in seed_tags
    assert "gatus" not in _tags(
        seed_task["ansible.builtin.include_role"].get("apply", {}).get("tags")
    )
    seed_block, seed_block_tags = role_tasks[
        "Seed Uptime Kuma's admin password in OpenBao"
    ]
    assert "gatus" not in seed_block_tags
    assert seed_block["no_log"] is True

    compose = role_tasks["Deploy status stack via docker compose"][0][
        "community.docker.docker_compose_v2"
    ]
    selected_services = _read(ROLE_VARS)["status_stack_compose_services"]
    assert compose["services"] == "{{ status_stack_compose_services | default(omit, true) }}"
    assert _selected_services(selected_services, ["gatus"]) == ["gatus"]
    assert _selected_services(selected_services, ["uptime_kuma"]) == [
        "uptime-kuma", "autokuma"
    ]
    assert _selected_services(selected_services, ["autokuma"]) == ["autokuma"]
    assert _selected_services(selected_services, ["status"]) == []
    assert _selected_services(selected_services, ["all"]) == []

    gatus_render = role_tasks["Render Gatus configuration"][0]
    assert gatus_render["notify"] == "Restart status stack"
    for password_task_name in (
        "Read any persisted Uptime Kuma admin password",
        "Read the persisted Uptime Kuma admin password",
        "Resolve the persisted Uptime Kuma password for Gatus",
    ):
        assert role_tasks[password_task_name][0]["no_log"] is True
    handler = next(
        task for task in _read(ROLE_HANDLERS)
        if task.get("name") == "Restart status stack"
    )
    handler_compose = handler["community.docker.docker_compose_v2"]
    assert handler_compose["services"] == compose["services"]
    assert handler_compose["recreate"] == "always"
    assert "gatus" in _tags(handler.get("tags"))
    assert compose_render["notify"] == "Restart status stack"


def test_gatus_compose_render_matches_full_run_using_read_only_password():
    context = {
        "status_stack_gatus_image": "ghcr.io/twin/gatus:test",
        "status_stack_gatus_container_name": "gatus",
        "status_stack_data_dir": "/srv/status-stack",
        "status_stack_gatus_data_dir": "/srv/status-stack/gatus/data",
        "status_stack_kuma_image": "louislam/uptime-kuma:test",
        "status_stack_kuma_container_name": "uptime-kuma",
        "status_stack_kuma_port": "3001",
        "status_stack_autokuma_image": "ghcr.io/bigboot/autokuma:test",
        "status_stack_autokuma_container_name": "autokuma",
        "status_stack_autokuma_static_monitors_dir": (
            "/srv/status-stack/autokuma/static-monitors"
        ),
        "status_stack_autokuma_kuma_url": "http://127.0.0.1:3001",
        "status_stack_kuma_admin_username": "admin",
    }
    environment = jinja2.Environment(
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )
    environment.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
    template = environment.from_string(COMPOSE_TEMPLATE.read_text(encoding="utf-8"))
    role_tasks = _named(list(_walk(_read(ROLE_TASKS))))
    stored_password_task = role_tasks[
        "Resolve the persisted Uptime Kuma password for Gatus"
    ][0]
    password_expression = stored_password_task["ansible.builtin.set_fact"][
        "status_stack_effective_kuma_password"
    ]
    stored_password = "fixture-password"
    stored_content = base64.b64encode(f"{stored_password}\n".encode()).decode()
    gatus_password = environment.from_string(password_expression).render(
        status_stack_kuma_pw_stored={"content": stored_content}
    )

    gatus_render = template.render(
        **context,
        status_stack_effective_kuma_password=gatus_password,
    )
    full_render = template.render(
        **context,
        status_stack_effective_kuma_password=stored_password,
    )
    assert gatus_render == full_render

    services = yaml.safe_load(gatus_render)["services"]
    assert set(services) == {"gatus", "uptime-kuma", "autokuma"}
    assert services["gatus"]["image"] == context["status_stack_gatus_image"]
    assert services["gatus"]["volumes"] == [
        "/srv/status-stack/gatus/config.yaml:/config/config.yaml:ro",
        "/srv/status-stack/gatus/data:/data",
    ]
    assert (
        services["autokuma"]["environment"]["AUTOKUMA__KUMA__PASSWORD"]
        == stored_password
    )
    guard_task = role_tasks[
        "Require a persisted Uptime Kuma password for a Gatus-only run"
    ][0]
    assert "Run the full status play first" in guard_task["ansible.builtin.fail"]["msg"]
    assert guard_task["when"] == [
        "status_stack_effective_kuma_password is not defined",
        "not status_stack_kuma_pw_stat.stat.exists",
    ]
    assert (
        stored_password_task["when"]
        == "status_stack_effective_kuma_password is not defined"
    )


def test_untagged_status_stack_still_contains_every_component():
    role_tasks = _named(list(_walk(_read(ROLE_TASKS))))
    auto_tasks = _named(list(_walk(_read(AUTOKUMA_TASKS))))
    all_names = set(role_tasks) | set(auto_tasks)
    assert {
        "Render Gatus configuration",
        "Deploy status stack via docker compose",
        "Verify Gatus answers /",
        "Read any persisted Uptime Kuma admin password",
        "Create Uptime Kuma initial admin",
        "Render status stack docker-compose",
        "Render and ship the AutoKuma static-monitor set",
        "Build the combined AutoKuma monitor list from monitor_targets",
        "Ship and extract the AutoKuma monitor set in one transfer",
    } <= all_names
    assert _read(ROLE_META)["dependencies"] == [{"role": "docker_engine"}]


def _list_tasks(playbook, tags=None):
    command = [
        "ansible-playbook",
        str(playbook),
        "-i",
        str(STATUS_INVENTORY),
        "--list-tasks",
    ]
    if tags is not None:
        command.extend(["--tags", tags])
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_ansible_lists_component_tasks_for_status_stack_tag_runs():
    for tags in ("gatus", "uptime_kuma", None):
        status_tasks = _list_tasks(PLAYBOOK, tags)
        assert "Include status_stack role" in status_tasks

    gatus_tasks = _list_tasks(ROLE_LIST_TASKS_PLAYBOOK, "gatus")
    assert "Render Gatus configuration" in gatus_tasks
    assert "Render status stack docker-compose" in gatus_tasks
    assert "Deploy status stack via docker compose" in gatus_tasks
    assert "Wait for Gatus HTTP port" in gatus_tasks
    assert "Verify Gatus answers /" in gatus_tasks
    assert "Read any persisted Uptime Kuma admin password" in gatus_tasks
    assert "Read the persisted Uptime Kuma admin password" in gatus_tasks
    assert "Require a persisted Uptime Kuma password for a Gatus-only run" in gatus_tasks
    assert "Resolve the persisted Uptime Kuma password for Gatus" in gatus_tasks
    assert "Seed Uptime Kuma's admin password in OpenBao" not in gatus_tasks
    assert "Seed the Uptime Kuma admin password through the shared seed_generated task" not in gatus_tasks
    assert "AutoKuma" not in gatus_tasks

    uptime_kuma_tasks = _list_tasks(ROLE_LIST_TASKS_PLAYBOOK, "uptime_kuma")
    assert "Render status stack docker-compose" in uptime_kuma_tasks
    assert "Read any persisted Uptime Kuma admin password" in uptime_kuma_tasks

    untagged_tasks = _list_tasks(ROLE_LIST_TASKS_PLAYBOOK)
    assert "Render status stack docker-compose" in untagged_tasks
    assert "Render Gatus configuration" in untagged_tasks
    assert "Render and ship the AutoKuma static-monitor set" in untagged_tasks
