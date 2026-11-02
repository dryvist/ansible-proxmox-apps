"""Parsed-YAML contract for separately selectable Grafana role parts."""

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]
PARTS = {
    "grafana_stack_deploy": "deploy",
    "grafana_stack_provisioning": "provisioning",
}


def _task_names(tasks):
    for task in tasks:
        if "name" in task:
            yield task["name"]
        for key in ("block", "rescue", "always"):
            yield from _task_names(task.get(key, []))


def _tasks(tasks):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key, []))


def test_grafana_tags_select_disjoint_parts_and_cover_every_role_task():
    role_main = yaml.safe_load(
        (REPO / "roles/grafana_stack/tasks/main.yml").read_text(encoding="utf-8")
    )
    imports = {
        task["ansible.builtin.import_tasks"]: set(task["tags"])
        for task in role_main
    }
    assert imports == {
        "deploy.yml": {"grafana", "grafana_stack_deploy"},
        "provisioning.yml": {"grafana", "grafana_stack_provisioning"},
    }

    names_by_part = {
        part: set(
            _task_names(
                yaml.safe_load(
                    (REPO / f"roles/grafana_stack/tasks/{filename}.yml").read_text(
                        encoding="utf-8"
                    )
                )
            )
        )
        for part, filename in PARTS.items()
    }
    assert names_by_part["grafana_stack_deploy"]
    assert names_by_part["grafana_stack_provisioning"]
    assert names_by_part["grafana_stack_deploy"].isdisjoint(
        names_by_part["grafana_stack_provisioning"]
    )
    for part, filename in PARTS.items():
        tasks = yaml.safe_load(
            (REPO / f"roles/grafana_stack/tasks/{filename}.yml").read_text(
                encoding="utf-8"
            )
        )
        for task in _tasks(tasks):
            include_role = task.get("ansible.builtin.include_role")
            if include_role:
                assert part in include_role.get("apply", {}).get("tags", [])

    site_imports = yaml.safe_load(
        (REPO / "playbooks/site/04-secrets-and-collab-apps.yml").read_text(
            encoding="utf-8"
        )
    )
    grafana_import = next(
        item
        for item in site_imports
        if item.get("import_playbook") == "04e-grafana-stack.yml"
    )
    assert grafana_import["name"] == "Grafana observability stack"
    playbook = yaml.safe_load(
        (REPO / "playbooks/site/04e-grafana-stack.yml").read_text(encoding="utf-8")
    )
    play = next(play for play in playbook if play.get("hosts") == "grafana_group")
    assert "grafana" in play["tags"]
    block_task = next(task for task in play["tasks"] if task.get("block"))
    block = block_task["block"]
    role_calls = {
        task["ansible.builtin.include_role"]["tasks_from"]: task
        for task in block
        if "ansible.builtin.include_role" in task
    }
    assert set(role_calls) == set(PARTS.values())

    for tag, part in PARTS.items():
        role_call = role_calls[part]
        assert role_call["tags"] == [tag]
        assert tag in role_call["ansible.builtin.include_role"]["apply"]["tags"]
        assert "grafana" in role_call["ansible.builtin.include_role"]["apply"]["tags"]
        assert role_call["ansible.builtin.include_role"]["tasks_from"] == part

    shared_tasks = [
        next(task for task in block if task.get("name") == "Gather facts"),
        next(
            task
            for task in block_task["rescue"]
            if task.get("name") == "Record isolated failure and continue"
        ),
    ]
    assert {task["name"] for task in shared_tasks} == {
        "Gather facts",
        "Record isolated failure and continue",
    }
    for task in shared_tasks:
        assert set(PARTS).issubset(task["tags"])
