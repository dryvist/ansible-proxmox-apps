"""App-agent publishers read exact leaves, validate TLS and hide bearer tokens."""

from app_agent_helpers import ROOT, _render, _task, _vikunja_defaults, _yaml


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
