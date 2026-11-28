# Run from the repository root with: python3 -m pytest tests --ignore=tests/e2e -v
"""Static contract for the per-calling-role Vikunja identities."""

from app_agent_helpers import _render, _task_tree, _vikunja_defaults, _yaml


ROLE_NAMES = {
    "workstation",
    "hermes",
    "pepper",
    "untrusted",
    "machines",
    "jobs",
    "inbox",
    "acceptance",
    "triage",
    "nightly",
    "windows",
}
PROJECT_SET_NAMES = {
    "domain",
    "work",
    "inbox",
    "windows",
    "jobs",
    "hermes_board",
    "donna_board",
    "acceptance",
}
LEGACY_TIER_NAMES = {"vikunja-read", "vikunja-write", "vikunja-clerk"}
# A bucket move is a task change; bucket create, update and delete are project writes and stay out.
PROJECT_READ_OR_MOVE = {
    "read_all",
    "read_one",
    "views_buckets",
    "views_buckets_tasks",
    "views_buckets_tasks_update",
}


def _role_permissions(row, defaults):
    value = row["permissions"]
    return _render(value, defaults) if isinstance(value, str) else value


def test_role_list_names_all_callers_and_declared_project_sets():
    defaults = _vikunja_defaults()
    rows = defaults["vikunja_agent_roles"]
    by_role = {row["role"]: row for row in rows}

    assert set(by_role) == ROLE_NAMES
    assert len(by_role) == len(rows)
    assert set(defaults["vikunja_agent_project_sets"]) == PROJECT_SET_NAMES
    assert all(ids == [] for ids in defaults["vikunja_agent_project_sets"].values())

    for row in rows:
        assert set(row["project_permissions"]) <= PROJECT_SET_NAMES
        assert set(row["project_permissions"].values()) <= {0, 1}


def test_create_only_roles_have_no_read_permission():
    defaults = _vikunja_defaults()
    rows = {row["role"]: row for row in defaults["vikunja_agent_roles"]}

    for role in ("untrusted", "inbox"):
        permissions = _role_permissions(rows[role], defaults)
        assert permissions == {"mcp": ["access"], "tasks": ["create"]}


def test_no_role_token_can_delete_tasks_or_write_projects():
    defaults = _vikunja_defaults()

    for row in defaults["vikunja_agent_roles"]:
        permissions = _role_permissions(row, defaults)
        assert not any(
            action.startswith("delete")
            for action in permissions.get("tasks", [])
        )
        for group, actions in permissions.items():
            if group.startswith("projects"):
                assert set(actions) <= PROJECT_READ_OR_MOVE


def test_every_role_token_may_reach_the_tool_server():
    defaults = _vikunja_defaults()

    for row in defaults["vikunja_agent_roles"]:
        assert _role_permissions(row, defaults)["mcp"] == ["access"]


def test_roles_are_off_until_named_in_the_enabled_list():
    defaults = _vikunja_defaults()

    assert defaults["vikunja_agent_roles_enabled"] == []
    assert all("enabled" not in row for row in defaults["vikunja_agent_roles"])


def test_legacy_tier_names_remain_unchanged():
    defaults = _vikunja_defaults()
    rows = defaults["vikunja_agent_tiers"]
    legacy = {row["id"]: row["username"] for row in rows}

    assert LEGACY_TIER_NAMES <= set(legacy)
    assert {
        "vikunja-read": "svc-agent-ro",
        "vikunja-write": "svc-agent-rw",
        "vikunja-clerk": "svc-agent-clerk",
    }.items() <= legacy.items()


def test_role_token_flow_includes_mcp_verification():
    token_tasks = _yaml("roles/vikunja/tasks/mcp_tokens.yml")
    assert any(
        task.get("ansible.builtin.include_tasks") == "mcp_token_one.yml"
        and "vikunja_agent_roles" in str(task)
        for task in _task_tree(token_tasks)
    )

    token_one = _yaml("roles/vikunja/tasks/mcp_token_one.yml")
    assert any(
        task.get("ansible.builtin.include_tasks") == "mcp_agent_role_verify.yml"
        and "vikunja_mcp_user.role" in str(task.get("when", ""))
        for task in _task_tree(token_one)
    )

    verification = _yaml("roles/vikunja/tasks/mcp_agent_role_verify.yml")
    verification_tasks = list(_task_tree(verification))
    assert any(
        task.get("name") == "Verify MCP tool listing for agent role"
        for task in verification_tasks
    )
    assert "/api/v2/mcp" in str(verification_tasks)


def test_role_verification_facts_never_read_a_sibling_key_of_the_same_task():
    # A fact set in one task is not visible to the other keys of that task.
    for task in _yaml("roles/vikunja/tasks/mcp_agent_role_verify.yml"):
        facts = task.get("ansible.builtin.set_fact", {})
        for key, value in facts.items():
            for sibling in facts:
                assert sibling == key or sibling not in str(value), (task["name"], key, sibling)


def test_active_rows_derive_user_and_store_names_from_the_role_name():
    defaults = _vikunja_defaults()
    assert _render(defaults["vikunja_agent_roles_active"], defaults) == []

    enabled = defaults | {"vikunja_agent_roles_enabled": ["workstation", "nightly"]}
    rows = {row["role"]: row for row in _render(defaults["vikunja_agent_roles_active"], enabled)}
    assert set(rows) == {"workstation", "nightly"}
    mount = defaults["vikunja_agent_tiers"][0]["openbao_mount"]
    assert {
        key: rows["nightly"][key]
        for key in ("username", "password_field", "openbao_mount", "openbao_path", "openbao_login_path", "token_field")
    } == {
        "username": "svc-agent-nightly",
        "password_field": "vikunja_agent_nightly_password",
        "openbao_mount": mount,
        "openbao_path": "vikunja-nightly",
        "openbao_login_path": "vikunja-nightly-login",
        "token_field": "VIKUNJA_AGENT_NIGHTLY_TOKEN",
    }
    assert rows["workstation"]["project_permissions"]["domain"] == 1
