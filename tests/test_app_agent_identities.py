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


def test_vikunja_agent_tiers_have_exact_identity_and_project_access():
    defaults = _vikunja_defaults()
    group_vars = _yaml("inventory/group_vars/vikunja_group.yml")
    tiers = {tier["id"]: tier for tier in defaults["vikunja_agent_tiers"]}
    assert set(tiers) == {"vikunja-read", "vikunja-write"}
    assert not {"svc-agent-ro", "svc-agent-rw"} & {
        user["username"] for user in defaults["vikunja_service_users"]
    }

    expected = {
        "vikunja-read": ("svc-agent-ro", "vikunja_agent_read_password", "VIKUNJA_AGENT_READ_TOKEN", 0),
        "vikunja-write": ("svc-agent-rw", "vikunja_agent_write_password", "VIKUNJA_AGENT_WRITE_TOKEN", 1),
    }
    for tier_id, (username, password_field, token_field, permission) in expected.items():
        tier = tiers[tier_id]
        assert tier["username"] == username
        assert tier["password_field"] == password_field
        assert tier["token_field"] == token_field
        assert tier["share_permission"] == permission
        assert _render(tier["project_allowlist"], defaults) == ["Hermes"]
        assert "bao_apps_secrets." + password_field in group_vars[password_field]
        assert "mandatory(" in group_vars[password_field]

    assert all(user["username"].startswith("svc-mcp-") for user in defaults["vikunja_mcp_token_users"])
    assert {user["kv_field"] for user in defaults["vikunja_mcp_token_users"][:2]} == {
        "VIKUNJA_MCP_TOKEN_RO", "VIKUNJA_MCP_TOKEN_RW"
    }

    access_tasks = _yaml("roles/vikunja/tasks/agent_read_access.yml")
    reconcile_dispatch = _task(access_tasks, "Reconcile each configured app-agent tier exactly")
    assert reconcile_dispatch["loop"] == "{{ vikunja_agent_tiers }}"
    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    regrant = _task(reconcile, "Regrant only the configured direct project shares to the tier account")
    assert regrant["vars"]["vikunja_share_grantee_username"] == "{{ vikunja_agent_tier.username }}"
    assert regrant["vars"]["vikunja_share_permission"] == "{{ vikunja_agent_tier.share_permission }}"
    assert regrant["vars"]["vikunja_share_project_titles"] == "{{ vikunja_agent_tier.project_allowlist }}"

    operator_tasks = _yaml("roles/vikunja/tasks/operator_access.yml")
    operator_share = _task(operator_tasks, "Share automation-owned projects with the operator, per owning account")
    assert "vikunja_share_project_titles" not in operator_share["vars"]
    operator_project_tasks = _yaml("roles/vikunja/tasks/operator_access_project.yml")
    assert not any(task.get("ansible.builtin.uri", {}).get("method") == "DELETE" for task in operator_project_tasks)

    filter_task = _task(
        _yaml("roles/vikunja/tasks/operator_access_one.yml"),
        "Filter the owned projects to the configured title allowlist",
    )
    projects = [{"id": 1, "title": "Hermes"}, {"id": 2, "title": "Sensitive"}]
    for tier in tiers.values():
        allowlist = _render(tier["project_allowlist"], defaults)
        filtered = _render(
            filter_task["ansible.builtin.set_fact"]["vikunja_owned_projects"],
            {"vikunja_owned_projects": projects, "vikunja_share_project_titles": allowlist},
        )
        assert [project["title"] for project in filtered] == allowlist


def test_vikunja_interactive_and_agent_tokens_publish_to_separate_leaves():
    defaults = _vikunja_defaults()
    tasks = _yaml("roles/vikunja/tasks/mcp_token_one.yml")
    resolve = _task(tasks, "Resolve token title, permissions, and OpenBao target for {{ vikunja_mcp_user.username }}")
    static_fields = resolve["ansible.builtin.set_fact"]["vikunja_mcp_token_static_fields"]
    shared = defaults["vikunja_mcp_token_users"][0]
    base_variables = {
        "vikunja_url_openbao_key": "VIKUNJA_MCP_URL",
        "vikunja_mcp_url": "https://vikunja.example.invalid/api/v1",
        "vikunja_token_openbao_mount": "secret",
        "vikunja_token_openbao_path": "ai/mcp/vikunja",
        "vikunja_mcp_token_mount": "secret",
        "vikunja_mcp_token_path": "ai/mcp/vikunja",
    }
    shared_fields = _render(static_fields, {**base_variables, "vikunja_mcp_user": shared})
    assert shared_fields == {"VIKUNJA_MCP_URL": "https://vikunja.example.invalid/api/v1"}

    tiers = {tier["id"]: tier for tier in defaults["vikunja_agent_tiers"]}
    read_tier = dict(tiers["vikunja-read"])
    read_tier["project_allowlist"] = ["Hermes"]
    read_fields = _render(
        static_fields,
        {
            **base_variables,
            "vikunja_mcp_user": read_tier,
            "vikunja_mcp_token_mount": "agent-tier",
            "vikunja_mcp_token_path": "vikunja-read",
        },
    )
    assert read_fields == {"VIKUNJA_AGENT_READ_ALLOWLIST": '["Hermes"]'}

    publish = next(task for task in tasks if str(task.get("name", "")).startswith("Publish the token to OpenBao"))
    assert "{{ vikunja_mcp_token_mount }}" in publish["ansible.builtin.uri"]["url"]
    assert "vikunja_mcp_token_static_fields" in publish["ansible.builtin.uri"]["body"]["data"]
    assert "vikunja_mcp_token_static_fields" in publish["when"]
    token_loop = _task(
        _yaml("roles/vikunja/tasks/mcp_tokens.yml"),
        "Mint and publish MCP and app-agent tokens per identity",
    )
    assert token_loop["loop"] == "{{ vikunja_mcp_token_users + vikunja_agent_tiers }}"


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
    assert "['agent-write', agent_write_user, agent_write_api_token, agent_write_prefs]" in ruby
    assert "agent_write_prefs = { 'permission' => %w[ticket.agent] }" in ruby
    assert "([admin] + service_users).reject { |u| u.id == agent_write_user.id }.each do |u|" in ruby

    role_tasks = _yaml("roles/zammad/tasks/main.yml")
    publish = _task(role_tasks, "Publish svc-agent-write Zammad connection to OpenBao")
    assert publish["ansible.builtin.include_tasks"] == "publish_mcp.yml"
    assert publish["vars"]["zammad_token_openbao_key"] == "ZAMMAD_AGENT_WRITE_TOKEN"
    assert publish["vars"]["zammad_publish_token"] == "{{ zammad_agent_write_api_token }}"
    assert publish["vars"]["zammad_token_openbao_mount"] == "agent-tier"
    assert publish["vars"]["zammad_token_openbao_path"] == "zammad-write"
    assert publish["vars"]["zammad_publish_url"] is False
