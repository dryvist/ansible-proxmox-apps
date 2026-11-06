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


def test_grafana_only_seeds_admin_password_and_plugin_provisioning_is_declarative():
    deploy_tasks = yaml.safe_load(
        (REPO / "roles/grafana_stack/tasks/deploy.yml").read_text(encoding="utf-8")
    )
    seed_block = next(
        task
        for task in deploy_tasks
        if task.get("name") == "Seed Grafana's admin password in OpenBao"
    )
    assert seed_block["no_log"] is True
    seed_task = next(
        task
        for task in _tasks(seed_block["block"])
        if task.get("name") == "Seed Grafana credentials through the shared seed_generated task"
    )
    assert seed_task["loop_control"]["loop_var"] == "grafana_stack_seed"
    seed_profiles = {profile["path"]: profile for profile in seed_task["loop"]}
    assert set(seed_profiles) == {"apps/grafana"}
    assert seed_profiles["apps/grafana"]["field"] == "grafana_admin_password"
    assert seed_profiles["apps/grafana"]["register"] == "grafana_stack_secret_seed"
    seed_vars = seed_task["vars"]
    assert seed_vars["openbao_secrets_seed_fields"] == [{
        "name": "{{ grafana_stack_seed.field }}",
        "length": "{{ grafana_stack_seed.length }}",
        "value": "{{ grafana_stack_seed.value }}",
    }]
    assert seed_vars["openbao_secrets_seed_path"] == "{{ grafana_stack_seed.path }}"
    assert seed_vars["openbao_secrets_seed_register"] == "{{ grafana_stack_seed.register }}"
    assert seed_vars["openbao_secrets_seed_local_values"] == (
        "{{ {grafana_stack_seed.field: grafana_stack_seed.value} }}"
    )
    effective_credentials = next(
        task["ansible.builtin.set_fact"]
        for task in deploy_tasks
        if task.get("name") == "Resolve Grafana credentials from OpenBao"
    )
    assert effective_credentials == {
        "grafana_stack_effective_admin_password": "{{ grafana_stack_secret_seed.grafana_admin_password }}",
    }
    assert deploy_tasks[0]["ansible.builtin.import_tasks"] == "llm_router.yml"

    provisioning_tasks = yaml.safe_load(
        (REPO / "roles/grafana_stack/tasks/provisioning.yml").read_text(
            encoding="utf-8"
        )
    )
    plugin_task = next(
        task
        for task in provisioning_tasks
        if task.get("name") == "Render Grafana LLM app plugin provisioning"
    )
    assert plugin_task["ansible.builtin.template"]["src"] == "llm-app.yml.j2"
    assert (
        plugin_task["ansible.builtin.template"]["dest"]
        == "{{ grafana_stack_data_dir }}/provisioning/plugins/llm-app.yml"
    )

    credential_task = next(
        task
        for task in deploy_tasks
        if task.get("name") == "Persist Grafana's LLM router credential"
    )
    assert credential_task["ansible.builtin.template"]["src"] == "llm-router.env.j2"
    assert credential_task["ansible.builtin.template"]["owner"] == "root"
    assert credential_task["ansible.builtin.template"]["mode"] == "0400"
    assert credential_task["no_log"] is True
    assert "when" not in credential_task
