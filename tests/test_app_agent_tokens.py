"""App-agent tokens use bounded scopes and shared idempotent publication."""

import subprocess

from app_agent_helpers import ROOT, _render, _task, _vikunja_defaults, _yaml


_MISSING = object()


def _token_include_runs(include_task, user, clerk_password=_MISSING):
    clerk_user = {"username": "svc-mcp-clerk"}
    if clerk_password is not _MISSING:
        clerk_user["password"] = clerk_password
    return _render(
        "{{ " + include_task["when"] + " }}",
        {
            "vikunja_mcp_user": user,
            "vikunja_service_users": [clerk_user],
        },
    )


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
    assert " ".join(token_loop["loop"].split()) == (
        "{{ vikunja_mcp_token_users + vikunja_clerk_token_users + vikunja_openhands_token_users + vikunja_agent_tiers }}"
    )


def test_vikunja_clerk_tokens_skip_when_service_password_is_empty():
    defaults = _vikunja_defaults()
    token_loop = _task(
        _yaml("roles/vikunja/tasks/mcp_tokens.yml"),
        "Mint and publish MCP and app-agent tokens per identity",
    )

    for password in (_MISSING, ""):
        for user in defaults["vikunja_clerk_token_users"]:
            assert _token_include_runs(token_loop, user, password) in (False, "False")


def test_vikunja_clerk_tokens_run_when_service_password_is_set():
    defaults = _vikunja_defaults()
    token_loop = _task(
        _yaml("roles/vikunja/tasks/mcp_tokens.yml"),
        "Mint and publish MCP and app-agent tokens per identity",
    )

    for user in defaults["vikunja_clerk_token_users"]:
        assert _token_include_runs(token_loop, user, "fixture-password") in (True, "True")


def test_vikunja_other_token_users_run_when_clerk_password_is_empty():
    defaults = _vikunja_defaults()
    token_loop = _task(
        _yaml("roles/vikunja/tasks/mcp_tokens.yml"),
        "Mint and publish MCP and app-agent tokens per identity",
    )
    other_users = (
        defaults["vikunja_mcp_token_users"]
        + defaults["vikunja_openhands_token_users"]
        + defaults["vikunja_agent_tiers"]
    )

    for user in other_users:
        assert _token_include_runs(token_loop, user, "") in (True, "True")


def test_vikunja_clerk_tokens_use_the_shared_idempotent_publisher():
    defaults = _vikunja_defaults()
    group_vars = _yaml("inventory/group_vars/vikunja_group.yml")
    users = {user["username"]: user for user in defaults["vikunja_service_users"]}
    assert users["svc-mcp-clerk"]["password"] == ""
    clerk_user = next(user for user in group_vars["vikunja_service_users"] if user["username"] == "svc-mcp-clerk")
    password_field = "svc_mcp_clerk_password"
    assert f"bao_apps_secrets.{password_field}" in clerk_user["password"]

    tracked_paths = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0")
    removed_env_name = f"VIKUNJA_{password_field.upper()}".encode()
    assert not any(
        removed_env_name in (ROOT / path).read_bytes()
        for path in tracked_paths
        if path
    )

    rows = defaults["vikunja_clerk_token_users"]
    assert [row["kv_field"] for row in rows] == [
        "VIKUNJA_MCP_TOKEN_VIKUNJA_CLERK",
        "VIKUNJA_MCP_HTTP_TOKEN_VIKUNJA_CLERK",
    ]
    assert {row["username"] for row in rows} == {"svc-mcp-clerk"}
    assert len({row["title"] for row in rows}) == 2
    assert all(row["permissions"] == "{{ vikunja_clerk_task_permissions }}" for row in rows)
    assert all("openbao_path" not in row for row in rows)
    assert defaults["vikunja_token_openbao_path"] == "ai/mcp/vikunja"
    assert defaults["vikunja_clerk_task_permissions"] == {
        "tasks": ["create", "read_all", "read_one", "update"]
    }

    resolve = _task(
        _yaml("roles/vikunja/tasks/mcp_token_one.yml"),
        "Resolve token title, permissions, and OpenBao target for {{ vikunja_mcp_user.username }}",
    )["ansible.builtin.set_fact"]
    for row, expected_field in zip(rows, (
        "VIKUNJA_MCP_TOKEN_VIKUNJA_CLERK",
        "VIKUNJA_MCP_HTTP_TOKEN_VIKUNJA_CLERK",
    ), strict=True):
        resolved_field = _render(resolve["vikunja_mcp_token_field"], {"vikunja_mcp_user": row})
        resolved_fields = _render(
            resolve["vikunja_mcp_token_fields"],
            {"vikunja_mcp_user": row, "vikunja_mcp_token_field": resolved_field},
        )
        assert resolved_field == expected_field
        assert resolved_fields == [expected_field]

    flow = _yaml("roles/vikunja/tasks/mcp_tokens.yml")
    loop = _task(flow, "Mint and publish MCP and app-agent tokens per identity")
    assert "vikunja_clerk_token_users" in loop["loop"]
    for name in (
        "Assert OpenBao write credentials are present",
        "Log in to Vikunja as admin to read the token route catalogue",
        "Fetch the API token route catalogue",
        "Mint and publish MCP and app-agent tokens per identity",
    ):
        assert _task(flow, name)["no_log"] is True
    token_tasks = _yaml("roles/vikunja/tasks/mcp_token_one.yml")
    mint = _task(token_tasks, "Mint API token for {{ vikunja_mcp_user.username }}")
    publish = next(task for task in token_tasks if str(task.get("name", "")).startswith("Publish the token to OpenBao"))
    assert "not vikunja_mcp_token_exists" in mint["when"]
    assert mint["no_log"] is True
    assert publish["no_log"] is True
    assert "vikunja_mcp_token_fields" in publish["ansible.builtin.uri"]["body"]["data"]
    assert all(task.get("no_log") is True for task in token_tasks)
    service_user = _task(
        _yaml("roles/vikunja/tasks/main.yml"),
        "Create Vikunja service users (idempotent — skipped if already present)",
    )
    assert service_user["no_log"] is True


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
    defaults = _vikunja_defaults()
    main = _yaml("roles/vikunja/tasks/main.yml")
    token_include = _task(main, "Validate MCP API token scopes and publish when enabled")
    assert token_include["when"] == ["not ansible_check_mode"]

    token_flow = _yaml("roles/vikunja/tasks/mcp_tokens.yml")
    per_identity = _task(token_flow, "Mint and publish MCP and app-agent tokens per identity")
    non_clerk_user = defaults["vikunja_mcp_token_users"][0]
    assert _token_include_runs(per_identity, non_clerk_user, "") in (True, "True")
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
