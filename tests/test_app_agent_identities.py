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
        assert _render(tier["project_allowlist"], defaults) == defaults[
            "vikunja_agent_read_allowlist" if permission == 0 else "vikunja_agent_write_allowlist"
        ]
        assert tier["openbao_mount"] == "agent-tier"
        assert tier["openbao_path"] == tier_id
        assert password_field not in group_vars
        assert "vikunja_agent_tier_secret_values" in defaults[password_field]

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
    assert regrant["vars"]["vikunja_share_project_ids"] == "{{ vikunja_agent_tier.project_allowlist }}"

    operator_tasks = _yaml("roles/vikunja/tasks/operator_access.yml")
    operator_share = _task(operator_tasks, "Share automation-owned projects with the operator, per owning account")
    assert "vikunja_share_project_titles" not in operator_share["vars"]
    operator_project_tasks = _yaml("roles/vikunja/tasks/operator_access_project.yml")
    assert not any(task.get("ansible.builtin.uri", {}).get("method") == "DELETE" for task in operator_project_tasks)

    filter_task = _task(
        _yaml("roles/vikunja/tasks/operator_access_one.yml"),
        "Filter the owned projects to the configured title allowlist",
    )
    id_filter_task = _task(
        _yaml("roles/vikunja/tasks/operator_access_one.yml"),
        "Filter the owned projects to the configured project ID allowlist",
    )
    assert defaults["vikunja_agent_read_allowlist"] == [64]
    assert defaults["vikunja_agent_write_allowlist"] == defaults["vikunja_agent_read_allowlist"]
    allowed_project_id = defaults["vikunja_agent_read_allowlist"][0]
    forbidden_project_id = allowed_project_id + 1
    projects = [
        {"id": project_id, "title": "Hermes" if project_id == allowed_project_id else "Sensitive"}
        for project_id in [*defaults["vikunja_agent_read_allowlist"], forbidden_project_id]
    ]
    for tier in tiers.values():
        allowlist = _render(tier["project_allowlist"], defaults)
        filtered_by_id = _render(
            id_filter_task["ansible.builtin.set_fact"]["vikunja_owned_projects"],
            {"vikunja_owned_projects": projects, "vikunja_share_project_ids": allowlist},
        )
        filtered_by_title = _render(
            filter_task["ansible.builtin.set_fact"]["vikunja_owned_projects"],
            {"vikunja_owned_projects": projects, "vikunja_share_project_titles": ["Hermes"]},
        )
        assert [project["id"] for project in filtered_by_id] == allowlist
        assert [project["title"] for project in filtered_by_title] == ["Hermes"]


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
    read_tier["project_allowlist"] = defaults["vikunja_agent_read_allowlist"]
    read_fields = _render(
        static_fields,
        {
            **base_variables,
            "vikunja_mcp_user": read_tier,
            "vikunja_mcp_token_mount": "agent-tier",
            "vikunja_mcp_token_path": "vikunja-read",
        },
    )
    assert read_fields == {
        "VIKUNJA_AGENT_READ_ALLOWLIST": _render("{{ vikunja_mcp_user.project_allowlist | to_json }}", {
            "vikunja_mcp_user": read_tier
        })
    }

    publish = next(task for task in tasks if str(task.get("name", "")).startswith("Publish the token to OpenBao"))
    assert "{{ vikunja_mcp_token_mount }}" in publish["ansible.builtin.uri"]["url"]
    assert "vikunja_mcp_token_static_fields" in publish["ansible.builtin.uri"]["body"]["data"]
    assert "vikunja_mcp_token_static_fields" in publish["when"]
    token_loop = _task(
        _yaml("roles/vikunja/tasks/mcp_tokens.yml"),
        "Mint and publish MCP and app-agent tokens per identity",
    )
    assert token_loop["loop"] == "{{ vikunja_mcp_token_users + vikunja_agent_tiers }}"


def test_vikunja_existing_token_scope_drift_is_deleted_and_replaced():
    tasks = _yaml("roles/vikunja/tasks/mcp_token_one.yml")
    list_existing = _task(tasks, "List existing API tokens for {{ vikunja_mcp_user.username }}")
    compare = _task(
        tasks,
        "Compare existing token scopes for {{ vikunja_mcp_user.username }}",
    )
    compare_text = str(compare["ansible.builtin.set_fact"])
    assert "vikunja_mcp_token_permissions.items()" in compare_text
    assert "_token.permissions" in compare_text
    assert "_actual.permissions != _expected.permissions" in compare_text
    assert "_token.id | int" in compare_text
    assert list_existing["ansible.builtin.uri"]["method"] == "GET"
    assert "/api/v1/tokens" in list_existing["ansible.builtin.uri"]["url"]
    assert compare["no_log"] is True
    assert tasks.index(list_existing) < tasks.index(compare)

    delete = next(
        task for task in tasks
        if "Delete same-title Vikunja tokens" in task.get("name", "")
    )
    assert delete["ansible.builtin.uri"]["method"] == "DELETE"
    assert "/api/v1/tokens/{{ item }}" in delete["ansible.builtin.uri"]["url"]
    assert delete["loop"] == "{{ vikunja_mcp_token_stale_ids }}"
    assert "vikunja_token_publish_openbao | bool" in delete["when"]
    assert "vikunja_mcp_token_stale_ids | length > 0" in delete["when"]
    assert delete["no_log"] is True
    assert tasks.index(compare) < tasks.index(delete)

    mint = _task(tasks, "Mint API token for {{ vikunja_mcp_user.username }}")
    assert "vikunja_token_publish_openbao | bool" in mint["when"]
    assert "not vikunja_mcp_token_exists" in mint["when"]
    assert mint["ansible.builtin.uri"]["body"]["permissions"] == "{{ vikunja_mcp_token_permissions }}"
    assert mint["no_log"] is True
    assert tasks.index(delete) < tasks.index(mint)


def test_vikunja_token_scope_validation_runs_without_publication():
    main = _yaml("roles/vikunja/tasks/main.yml")
    token_include = _task(main, "Validate MCP API token scopes and publish when enabled")
    assert token_include["when"] == ["not ansible_check_mode"]

    token_flow = _yaml("roles/vikunja/tasks/mcp_tokens.yml")
    per_identity = _task(token_flow, "Mint and publish MCP and app-agent tokens per identity")
    assert "when" not in per_identity
    assert "vikunja_token_publish_openbao | bool" in _task(
        token_flow, "Assert OpenBao write credentials are present"
    )["when"]

    identity_tasks = _yaml("roles/vikunja/tasks/mcp_token_one.yml")
    for name in (
        "Log in to Vikunja as {{ vikunja_mcp_user.username }}",
        "List existing API tokens for {{ vikunja_mcp_user.username }}",
        "Compare existing token scopes for {{ vikunja_mcp_user.username }}",
    ):
        task = _task(identity_tasks, name)
        assert "when" not in task
        assert "vikunja_token_publish_openbao" not in str(task)

    for name in (
        "Delete same-title Vikunja tokens with unauthorized scopes for {{ vikunja_mcp_user.username }}",
        "Mint API token for {{ vikunja_mcp_user.username }}",
        "Read current OpenBao secret at {{ vikunja_mcp_token_path }}",
        "Publish the token to OpenBao for {{ vikunja_mcp_user.username }}",
    ):
        assert "vikunja_token_publish_openbao | bool" in str(_task(identity_tasks, name)["when"])


def test_zammad_agent_write_identity_uses_its_generated_token_and_publisher():
    defaults = _yaml("roles/zammad/defaults/main/00-install-db-ai.yml")
    group_vars = (ROOT / "inventory/group_vars/zammad_group.yml").read_text(encoding="utf-8")
    bootstrap_tasks = _yaml("roles/zammad/tasks/main/nginx_and_bootstrap.yml")
    bootstrap_env = _task(bootstrap_tasks, "Run the idempotent Zammad bootstrap")["environment"]
    entrypoint = (ROOT / "roles/zammad/files/zammad_bootstrap.rb").read_text(encoding="utf-8")
    fragments = ROOT / "roles/zammad/files/zammad_bootstrap"
    ruby = "\n".join(path.read_text(encoding="utf-8") for path in sorted(fragments.glob("*.rb")))

    assert defaults["zammad_agent_write_email"].endswith("@{{ tofu_data.domain }}")
    assert "zammad_agent_tier_secret_values" in defaults["zammad_agent_write_api_token"]
    assert "lookup('env', 'ZAMMAD_AGENT_WRITE_API_TOKEN')" not in defaults["zammad_agent_write_api_token"]
    assert "zammad_agent_write_api_token" not in group_vars
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
    assert "agent_role_permission_names = %w[ticket.agent knowledge_base.editor]" in ruby
    assert "([admin] + service_users).reject { |u| u.id == agent_write_user.id }.each do |u|" in ruby

    role_tasks = _yaml("roles/zammad/tasks/main.yml")
    publish = _task(role_tasks, "Publish svc-agent-write Zammad connection to OpenBao")
    assert publish["ansible.builtin.include_tasks"] == "publish_mcp.yml"
    assert publish["vars"]["zammad_token_openbao_key"] == "ZAMMAD_AGENT_WRITE_TOKEN"
    assert publish["vars"]["zammad_publish_token"] == "{{ zammad_agent_write_api_token }}"
    assert publish["vars"]["zammad_token_openbao_mount"] == "agent-tier"
    assert publish["vars"]["zammad_token_openbao_path"] == "zammad-write"
    assert publish["vars"]["zammad_publish_url"] is False

    publisher_tasks = _yaml("roles/zammad/tasks/publish_mcp.yml")
    token_guard = _task(
        publisher_tasks,
        "Assert the Zammad token is present before publishing {{ zammad_token_openbao_path }}",
    )
    token_condition = token_guard["ansible.builtin.assert"]["that"][0]
    assert _render("{{ " + token_condition + " }}", {"zammad_publish_token": ""}) is False
    assert _render("{{ " + token_condition + " }}", {"zammad_publish_token": "fixture-token"}) is True
    publisher_write = _task(
        publisher_tasks,
        "Publish the connection to OpenBao at {{ zammad_token_openbao_path }}",
    )
    assert publisher_tasks.index(token_guard) < publisher_tasks.index(publisher_write)
    assert publisher_write["ansible.builtin.uri"]["method"] == "POST"

    verification = _yaml("roles/zammad/tasks/verify_agent_write_rights.yml")
    role_read = _task(verification, "Read the Agent role permissions as the administrator")
    assert "/api/v1/roles/{{ zammad_agent_write_agent_role_ids | first }}?expand=true" in role_read["ansible.builtin.uri"]["url"]
    assert role_read["no_log"] is True
    permission_readback = _task(verification, "Resolve expected role and token permissions from the bootstrap source")
    assert "10-admin-and-users.rb" in permission_readback["ansible.builtin.set_fact"]["zammad_agent_write_expected_role_permission_names"]
    assert "20-groups-and-tokens.rb" in permission_readback["ansible.builtin.set_fact"]["zammad_agent_write_expected_token_permission_names"]
    assert "ZAMMAD_AGENT_WRITE_TOKEN_PERMISSIONS=" in permission_readback["ansible.builtin.set_fact"]["zammad_agent_write_token_row_permission_names"]
    assert "zammad_agent_write_effective_role_permission_names ==" in str(
        _task(verification, "Assert exact Agent role permissions and svc-agent-write token scope")
    )
    assert "zammad_agent_write_token_row_permission_names ==" in str(
        _task(verification, "Assert exact Agent role permissions and svc-agent-write token scope")
    )
    assert any("admin endpoints" in task.get("name", "") for task in verification)
    assert any("refused on every admin endpoint" in task.get("name", "") for task in verification)


def test_app_agent_fields_are_read_only_from_their_exact_agent_tier_leaves():
    vikunja_defaults = _vikunja_defaults()
    vikunja_group_vars = _yaml("inventory/group_vars/vikunja_group.yml")
    vikunja_reads = _yaml("roles/vikunja/tasks/read_agent_tier_values.yml")
    vikunja_login_task = _task(vikunja_reads, "Read each app-agent password from its provisioner-only login leaf")
    vikunja_token_task = _task(vikunja_reads, "Read each existing app-agent token from its token leaf")
    vikunja_assert = _task(vikunja_reads, "Require every enabled tier login leaf and password field to exist")
    assert vikunja_login_task["ansible.builtin.uri"]["url"].endswith(
        "/v1/{{ vikunja_agent_tier.openbao_mount }}/data/{{ vikunja_agent_tier.openbao_login_path }}"
    )
    assert vikunja_token_task["ansible.builtin.uri"]["url"].endswith(
        "/v1/{{ vikunja_agent_tier.openbao_mount }}/data/{{ vikunja_agent_tier.openbao_path }}"
    )
    assert vikunja_login_task["loop"] == vikunja_token_task["loop"] == "{{ vikunja_agent_tiers }}"
    assert vikunja_login_task["no_log"] is True
    assert vikunja_token_task["no_log"] is True
    assert vikunja_assert["no_log"] is True
    assert "item.status | default(0) == 200" in str(vikunja_assert["ansible.builtin.assert"]["that"])
    assert "item.vikunja_agent_tier.token_field" in str(
        _task(vikunja_reads, "Store existing app-agent tokens from their token leaves")
    )

    zammad_defaults = _yaml("roles/zammad/defaults/main/00-install-db-ai.yml")
    zammad_group_vars = (ROOT / "inventory/group_vars/zammad_group.yml").read_text(encoding="utf-8")
    zammad_reads = _yaml("roles/zammad/tasks/read_agent_tier_values.yml")
    zammad_uri = next(task for task in zammad_reads if "ansible.builtin.uri" in task)
    zammad_assert = next(
        task for task in zammad_reads
        if task.get("name") == "Require the svc-agent-write tier leaf and token field to exist"
    )
    assert zammad_uri["ansible.builtin.uri"]["url"].endswith("/v1/agent-tier/data/zammad-write")
    assert zammad_uri["ansible.builtin.uri"]["status_code"] == [200, 403, 404]
    assert zammad_uri["no_log"] is True
    assert zammad_assert["no_log"] is True
    for field in (
        "vikunja_agent_read_password",
        "vikunja_agent_write_password",
        "zammad_agent_write_api_token",
    ):
        assert field not in vikunja_group_vars
        assert field not in zammad_group_vars
    assert "bao_apps_secrets" not in str(vikunja_defaults["vikunja_agent_read_password"])
    assert "bao_apps_secrets" not in str(vikunja_defaults["vikunja_agent_write_password"])
    assert "bao_apps_secrets" not in str(zammad_defaults["zammad_agent_write_api_token"])


def test_direct_share_cleanup_uses_owner_login_not_tier_token():
    tasks = _yaml("roles/vikunja/tasks/agent_revoke_direct_share.yml")
    owner_login = _task(tasks, "Log in to the owner of project {{ vikunja_agent_project.id }}")
    assert "vikunja_project_share_owner_password_map" in str(owner_login["ansible.builtin.uri"]["body"])
    assert owner_login["no_log"] is True
    for name in (
        "List direct user shares on project {{ vikunja_agent_project.id }}",
        "Remove the tier's direct share on project {{ vikunja_agent_project.id }}",
    ):
        task = _task(tasks, name)
        authorization = task["ansible.builtin.uri"]["headers"]["Authorization"]
        assert authorization == "Bearer {{ vikunja_agent_share_owner_login.json.token }}"
        assert "vikunja_agent_tier_login" not in authorization
        assert task["no_log"] is True


def test_openbao_publishers_validate_tls_with_the_shared_ca_bundle():
    def task_nodes(value):
        if isinstance(value, list):
            for item in value:
                yield from task_nodes(item)
        elif isinstance(value, dict):
            yield value
            for key in ("block", "rescue", "always"):
                if key in value:
                    yield from task_nodes(value[key])

    for role in ("vikunja", "zammad"):
        openbao_uris = []
        for path in (ROOT / f"roles/{role}/tasks").rglob("*.yml"):
            for task in task_nodes(_yaml(str(path.relative_to(ROOT)))):
                uri = task.get("ansible.builtin.uri", {})
                if "openbao" in str(uri.get("url", "")).lower() or "token_openbao_addr" in str(uri.get("url", "")):
                    openbao_uris.append((path, task, uri))
        assert openbao_uris
        for _path, task, uri in openbao_uris:
            assert uri.get("validate_certs") is not False
            assert uri.get("ca_path") == "{{ openbao_ca_path }}"
            assert task.get("no_log") is True


def test_hermes_bridge_share_requests_hide_bearer_tokens():
    tasks = _yaml("roles/vikunja/tasks/hermes_bridge_share_one.yml")
    token_requests = [
        task for task in tasks
        if "Authorization" in task.get("ansible.builtin.uri", {}).get("headers", {})
    ]
    assert len(token_requests) == 3
    assert all(task.get("no_log") is True for task in token_requests)
