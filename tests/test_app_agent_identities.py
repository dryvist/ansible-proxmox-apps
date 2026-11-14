"""App-agent identities have exact project access and ownership boundaries."""

from app_agent_helpers import _render, _task, _vikunja_defaults, _yaml


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


def test_vikunja_tier_revoke_loop_skips_projects_the_tier_owns():
    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    revoke = _task(reconcile, "Remove every direct user share held by the tier account")
    projects = [
        {"id": 87, "title": "Inbox", "owner": {"username": "svc-agent-ro"}},
        {"id": 12, "title": "Shared", "owner": {"username": "svc-mcp-rw"}},
    ]
    looped = _render(
        revoke["loop"],
        {"vikunja_agent_visible_projects": projects, "vikunja_agent_tier": {"username": "svc-agent-ro"}},
    )
    assert [project["id"] for project in looped] == [12]


def test_vikunja_tier_visibility_check_ignores_projects_the_tier_owns():
    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    check = _task(reconcile, "Assert the tier account can see exactly its project allowlist")
    readback = {
        "results": [
            {
                "json": [
                    {"id": 87, "title": "Inbox", "owner": {"username": "svc-agent-ro"}},
                    {"id": 12, "title": "Shared", "owner": {"username": "svc-mcp-rw"}},
                ]
            }
        ]
    }
    tier = {"username": "svc-agent-ro", "project_allowlist": [12]}
    context = {"vikunja_agent_projects_readback": readback, "vikunja_agent_tier": tier}
    assert _render("{{ " + check["ansible.builtin.assert"]["that"][0] + " }}", context) in (True, "True")
    tier["project_allowlist"] = [12, 13]
    assert _render("{{ " + check["ansible.builtin.assert"]["that"][0] + " }}", context) in (False, "False")


def test_vikunja_tier_permission_check_skips_projects_the_tier_owns():
    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    read = _task(reconcile, "Read the effective permission on each visible project as the tier account")
    readback = {
        "results": [
            {
                "json": [
                    {"id": 87, "title": "Inbox", "owner": {"username": "svc-agent-ro"}},
                    {"id": 12, "title": "Shared", "owner": {"username": "svc-mcp-rw"}},
                ]
            }
        ]
    }
    looped = _render(
        read["loop"],
        {"vikunja_agent_projects_readback": readback, "vikunja_agent_tier": {"username": "svc-agent-ro"}},
    )
    assert [int(project_id) for project_id in looped] == [12]
