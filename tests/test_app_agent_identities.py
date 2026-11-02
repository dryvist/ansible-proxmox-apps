"""The app-agent credentials have dedicated identities and bounded access."""

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]


def _yaml(relative_path: str):
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def _vikunja_defaults():
    merged = {}
    for path in sorted((ROOT / "roles/vikunja/defaults/main").glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return merged


def _render(value, variables: dict):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(value))


def _task(tasks: list[dict], name: str) -> dict:
    return next(task for task in tasks if task.get("name") == name)


def test_vikunja_agent_read_user_has_an_allowlisted_read_share_and_own_token():
    defaults = _vikunja_defaults()
    group_vars = _yaml("inventory/group_vars/vikunja_group.yml")
    service_user = next(user for user in defaults["vikunja_service_users"] if user["username"] == "svc-agent-ro")
    token_user = next(user for user in defaults["vikunja_mcp_token_users"] if user["username"] == "svc-agent-ro")
    existing_ro = next(user for user in defaults["vikunja_mcp_token_users"] if user["username"] == "svc-mcp-ro")
    group_user = next(user for user in group_vars["vikunja_service_users"] if user["username"] == "svc-agent-ro")

    assert service_user["password"] == "{{ lookup('env', 'VIKUNJA_AGENT_READ_PASSWORD') }}"
    assert "bao_apps_secrets.vikunja_agent_read_password" in group_user["password"]
    assert "mandatory(" in group_user["password"]
    assert defaults["vikunja_agent_read_allowlist"] == ["Hermes"]
    assert token_user == {
        "username": "svc-agent-ro",
        "readonly": True,
        "kv_field": "VIKUNJA_AGENT_READ_TOKEN",
    }
    assert existing_ro["readonly"] is True
    assert existing_ro["kv_field"] == "VIKUNJA_MCP_TOKEN_RO"

    share_tasks = _yaml("roles/vikunja/tasks/agent_read_access.yml")
    share = _task(share_tasks, "Share allowlisted projects with the read-only agent, per owning account")
    assert share["vars"]["vikunja_share_grantee_username"] == "svc-agent-ro"
    assert share["vars"]["vikunja_share_permission"] == 0
    assert share["vars"]["vikunja_share_project_titles"] == "{{ vikunja_agent_read_allowlist }}"
    operator_tasks = _yaml("roles/vikunja/tasks/operator_access.yml")
    operator_share = _task(operator_tasks, "Share automation-owned projects with the operator, per owning account")
    assert "vikunja_share_project_titles" not in operator_share["vars"]

    reconcile = _yaml("roles/vikunja/tasks/operator_access_one.yml")
    filter_task = _task(reconcile, "Filter the owned projects to the configured title allowlist")
    projects = [
        {"id": 1, "title": "Hermes"},
        {"id": 2, "title": "Sensitive"},
    ]
    filtered = _render(
        filter_task["ansible.builtin.set_fact"]["vikunja_owned_projects"],
        {"vikunja_owned_projects": projects, "vikunja_share_project_titles": defaults["vikunja_agent_read_allowlist"]},
    )
    assert [project["title"] for project in filtered] == defaults["vikunja_agent_read_allowlist"]


def test_vikunja_shared_path_publishes_the_read_allowlist_beside_the_url():
    defaults = _vikunja_defaults()
    publish = next(
        task
        for task in _yaml("roles/vikunja/tasks/mcp_token_one.yml")
        if str(task.get("name", "")).startswith("Publish the token to OpenBao")
    )
    variables = {
        "vikunja_url_openbao_key": "VIKUNJA_MCP_URL",
        "vikunja_mcp_url": "https://vikunja.example.invalid",
        "vikunja_agent_read_allowlist": defaults["vikunja_agent_read_allowlist"],
    }
    shared = _render(publish["vars"]["vikunja_mcp_shared_fields"], variables)
    assert shared == {
        "VIKUNJA_MCP_URL": "https://vikunja.example.invalid",
        "VIKUNJA_AGENT_READ_ALLOWLIST": '["Hermes"]',
    }
    # The write fires when any shared field drifts, not only the URL.
    assert "vikunja_mcp_shared_fields" in publish["when"]


def test_zammad_agent_write_identity_uses_its_generated_token_and_publisher():
    defaults = _yaml("roles/zammad/defaults/main/00-install-db-ai.yml")
    group_vars = (ROOT / "inventory/group_vars/zammad_group.yml").read_text(encoding="utf-8")
    bootstrap_tasks = _yaml("roles/zammad/tasks/main/nginx_and_bootstrap.yml")
    bootstrap_env = _task(bootstrap_tasks, "Run the idempotent Zammad bootstrap")["environment"]
    entrypoint = (ROOT / "roles/zammad/files/zammad_bootstrap.rb").read_text(encoding="utf-8")
    fragments = ROOT / "roles/zammad/files/zammad_bootstrap"
    ruby = "\n".join(path.read_text(encoding="utf-8") for path in sorted(fragments.glob("*.rb")))

    assert defaults["zammad_agent_write_email"].endswith("@{{ tofu_data.domain }}")
    assert defaults["zammad_agent_write_api_token"] == "{{ lookup('env', 'ZAMMAD_AGENT_WRITE_API_TOKEN') }}"
    assert "bao_apps_secrets.zammad_agent_write_api_token" in group_vars
    assert "ansible_bootstrap" in entrypoint
    assert "bootstrap_binding = binding" in entrypoint
    assert "eval(File.read(bootstrap_fragment), bootstrap_binding, bootstrap_fragment)" in entrypoint
    stage_fragments = _task(bootstrap_tasks, "Stage the Zammad bootstrap fragments on the target")
    assert stage_fragments["ansible.builtin.copy"]["src"] == "zammad_bootstrap/"
    assert stage_fragments["ansible.builtin.copy"]["dest"] == "{{ zammad_root }}/ansible_bootstrap/"
    assert bootstrap_env["ZAMMAD_AGENT_WRITE_EMAIL"] == "{{ zammad_agent_write_email }}"
    assert bootstrap_env["ZAMMAD_AGENT_WRITE_API_TOKEN"] == "{{ zammad_agent_write_api_token }}"
    assert "zammad_agent_write_api_token | length > 0" in str(
        _task(bootstrap_tasks, "Validate the bootstrap secrets are present")["ansible.builtin.assert"]["that"]
    )

    assert "agent_write_email = env!('ZAMMAD_AGENT_WRITE_EMAIL')" in ruby
    assert "agent_write_api_token = env!('ZAMMAD_AGENT_WRITE_API_TOKEN')" in ruby
    assert "[agent_write_email, 'Service', 'Agent Write', agent_role]" in ruby
    assert "['agent-write', service_users[5], agent_write_api_token, agent_write_prefs]" in ruby
    assert "agent_write_prefs = { 'permission' => %w[ticket.agent] }" in ruby
    assert "([admin] + service_users).each do |u|" in ruby

    role_tasks = _yaml("roles/zammad/tasks/main.yml")
    publish = _task(role_tasks, "Publish svc-agent-write Zammad connection to OpenBao")
    assert publish["ansible.builtin.include_tasks"] == "publish_mcp.yml"
    assert publish["vars"]["zammad_token_openbao_key"] == "ZAMMAD_AGENT_WRITE_TOKEN"
    assert publish["vars"]["zammad_publish_token"] == "{{ zammad_agent_write_api_token }}"
