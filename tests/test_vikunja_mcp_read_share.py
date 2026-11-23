"""The read-only tracker account gets a read share on every owned project.

svc-mcp-ro must read every project the read-write automation account owns,
including top-level projects. The share is granted per project by the shared
reconciler (operator_access_one.yml), acting as the owner through the owner
credential map; the project list is derived at run time from the owner's own
project pages, never pinned by id, so an explicit grant survives reparenting
where an inherited one would not.

These render the REAL expressions out of the defaults and task files.
"""

from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_DIR = ROOT / "roles/vikunja/defaults/main"
MAIN = "roles/vikunja/tasks/main.yml"
READ_ACCESS = "roles/vikunja/tasks/mcp_read_access.yml"
OPERATOR_ONE = "roles/vikunja/tasks/operator_access_one.yml"

MAP = "Build the owner credential map for the tracker read share"
RESOLVE = "Resolve the read-only tracker user from vikunja_service_users"
NO_USER_NOTE = "Note the read-only tracker account is not provisioned"
SHARE = "Share every read-write-owned project with the read-only tracker account"
MAIN_INCLUDE = "Reconcile read shares for the read-only tracker service account"
MAIN_CHECK_NOTE = "Note the tracker read shares are not evaluated in check mode"
SELECT = "Select the projects owned by {{ vikunja_share_owner }}"


def _yaml(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def defaults():
    merged = {}
    for path in sorted(DEFAULTS_DIR.glob("*.yml")):
        merged.update(_yaml(path) or {})
    return merged


def find(name, rel):
    for task in _yaml(rel):
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {rel}")


def _render(value, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(value))


def _render_expr(condition, variables):
    """Render a bare `when` condition: the source is not wrapped in {{ }}."""
    return _render("{{ " + condition + " }}", variables)


# --- defaults: Read permission, owners by username, no pinned project ids -----


def test_the_tracker_share_permission_is_read():
    assert defaults()["vikunja_mcp_ro_share_permission"] == 0


def test_the_tracker_share_owners_are_the_read_write_account_only():
    assert defaults()["vikunja_mcp_ro_share_owner_usernames"] == ["svc-mcp-rw"]


def test_the_share_carries_no_allowlist_so_projects_are_derived_at_run_time():
    vars_ = find(SHARE, READ_ACCESS)["vars"]
    assert "vikunja_share_project_ids" not in vars_
    assert "vikunja_share_project_titles" not in vars_


# --- the tracker credential comes from the canonical service-user sources -----


def test_the_tracker_is_a_declared_service_user_with_the_env_default_password():
    users = [u for u in defaults()["vikunja_service_users"] if u["username"] == "svc-mcp-ro"]
    (user,) = users
    assert user["password"] == "{{ lookup('env', 'VIKUNJA_SVC_MCP_RO_PASSWORD') }}"


def test_the_group_vars_tracker_password_is_bao_first_and_fails_closed():
    group_vars = _yaml("inventory/group_vars/vikunja_group.yml")
    (user,) = [u for u in group_vars["vikunja_service_users"] if u["username"] == "svc-mcp-ro"]
    variables = {"bao_apps_secrets": {"svc_mcp_ro_password": "pw-from-bao"}}
    assert _render(user["password"], variables) == "pw-from-bao"
    with pytest.raises(Exception):
        _render(user["password"], {"bao_apps_secrets": {}})


def test_the_resolver_selects_the_tracker_row_from_the_service_users():
    fact = find(RESOLVE, READ_ACCESS)["ansible.builtin.set_fact"]["vikunja_mcp_ro_user"]
    variables = {
        "vikunja_service_users": [
            {"username": "svc-mcp-rw", "password": "pw-rw"},
            {"username": "svc-mcp-ro", "password": "pw-ro"},
        ]
    }
    assert _render(fact, variables) == {"username": "svc-mcp-ro", "password": "pw-ro"}


def test_the_resolver_returns_an_empty_row_when_the_tracker_is_undeclared():
    fact = find(RESOLVE, READ_ACCESS)["ansible.builtin.set_fact"]["vikunja_mcp_ro_user"]
    variables = {"vikunja_service_users": [{"username": "svc-mcp-rw", "password": "pw-rw"}]}
    assert _render(fact, variables) == {}


# --- the shared reconciler is reused, never copied ------------------------------


def test_the_share_reuses_the_shared_reconciler():
    task = find(SHARE, READ_ACCESS)
    assert task["ansible.builtin.include_tasks"] == "operator_access_one.yml"
    assert task["loop_control"]["loop_var"] == "vikunja_share_owner"


def test_the_share_loop_targets_the_configured_owners():
    loop = find(SHARE, READ_ACCESS)["loop"]
    assert _render(loop, defaults()) == ["svc-mcp-rw"]


def test_the_owner_credential_map_is_loaded_before_the_share():
    tasks = _yaml(READ_ACCESS)
    names = [task.get("name") for task in tasks]
    load = tasks[names.index(MAP)]
    assert load["ansible.builtin.include_tasks"] == "project_share_owner_password_map.yml"
    assert names.index(MAP) < names.index(SHARE)


def test_the_share_drives_the_reconciler_with_the_tracker_pair():
    rendered = {key: _render(value, defaults()) for key, value in find(SHARE, READ_ACCESS)["vars"].items()}
    assert rendered["vikunja_share_grantee_username"] == "svc-mcp-ro"
    assert rendered["vikunja_share_permission"] == 0


def test_the_share_takes_the_owner_password_from_the_map():
    assert "vikunja_share_owner_password" not in find(SHARE, READ_ACCESS)["vars"]


def _share_when(*, ro_password="pw", owner_password="pw", owner="svc-mcp-rw"):
    variables = {
        "vikunja_mcp_ro_user": {"password": ro_password},
        "vikunja_share_owner": owner,
        "vikunja_project_share_owner_password_map": {"svc-mcp-rw": owner_password},
    }
    return all(bool(_render_expr(condition, variables)) for condition in find(SHARE, READ_ACCESS)["when"])


def test_the_share_runs_when_both_credentials_are_set():
    assert _share_when() is True


def test_the_share_skips_without_a_provisioned_tracker_password():
    assert _share_when(ro_password="") is False


def test_the_share_skips_an_owner_without_a_resolvable_credential():
    assert _share_when(owner_password="") is False


def test_the_share_skips_an_owner_outside_the_credential_map():
    assert _share_when(owner="someone-else") is False


def test_a_missing_tracker_service_user_is_announced_by_its_task():
    note = find(NO_USER_NOTE, READ_ACCESS)
    assert "not provisioned" in note["name"]
    assert bool(_render_expr(note["when"], {"vikunja_mcp_ro_user": {}})) is True
    variables = {"vikunja_mcp_ro_user": {"password": "pw"}}
    assert bool(_render_expr(note["when"], variables)) is False


# --- additive only: no revoke anywhere on this path -----------------------------


def test_the_tracker_share_path_never_revokes():
    for task in _yaml(READ_ACCESS) or []:
        assert (task.get("ansible.builtin.uri") or {}).get("method") != "DELETE"


# --- the owned-project list is derived at run time, top level included ----------


def test_the_reconciler_selects_every_owned_project_top_level_included():
    # A top-level owned project (no parent), a nested owned project, and a
    # project merely shared with the owner (owned by someone else): exactly
    # the owned projects are shared, whatever their depth in the tree.
    selection = find(SELECT, OPERATOR_ONE)["ansible.builtin.set_fact"]["vikunja_owned_projects"]
    projects = [
        {"id": 55, "title": "Top level", "owner": {"username": "svc-mcp-rw"}},
        {"id": 64, "title": "Nested", "parent_project_id": 55, "owner": {"username": "svc-mcp-rw"}},
        {"id": 7, "title": "Shared with the owner", "owner": {"username": "admin"}},
    ]
    variables = {
        "vikunja_share_projects_p1": {"json": projects[:2]},
        "vikunja_share_projects_rest": {"results": [{"json": projects[2:]}]},
        "vikunja_share_owner": "svc-mcp-rw",
    }
    selected = _render(selection, variables)
    assert [project["id"] for project in selected] == [55, 64]


def test_without_an_allowlist_the_id_filter_is_skipped():
    # The tracker include passes no vikunja_share_project_ids, so the
    # reconciler's allowlist filter must stay out of the way entirely.
    filter_task = find("Filter the owned projects to the configured project ID allowlist", OPERATOR_ONE)
    assert filter_task["when"] == "vikunja_share_project_ids is defined"
    assert not bool(_render_expr(filter_task["when"], {"vikunja_owned_projects": []}))


# --- wiring in main.yml ----------------------------------------------------------


def test_the_include_sits_after_the_service_users_are_created():
    names = [task.get("name") for task in _yaml(MAIN)]
    assert names.index(
        "Create Vikunja service users (idempotent — skipped if already present)"
    ) < names.index(MAIN_INCLUDE)


def test_the_include_points_at_the_tracker_task_file():
    include = find(MAIN_INCLUDE, MAIN)
    assert include["ansible.builtin.include_tasks"] == "mcp_read_access.yml"
    assert include["no_log"] is True
    assert include["tags"] == "vikunja_mcp_read_access"


def test_the_include_is_gated_on_check_mode():
    when = find(MAIN_INCLUDE, MAIN)["when"]
    assert bool(_render_expr(when[0], {"ansible_check_mode": False})) is True
    assert bool(_render_expr(when[0], {"ansible_check_mode": True})) is False


def test_the_check_mode_skip_is_announced():
    note = find(MAIN_CHECK_NOTE, MAIN)
    assert "check mode" in note["name"]
    assert note["tags"] == "vikunja_mcp_read_access"
    assert bool(_render_expr(note["when"], {"ansible_check_mode": True})) is True
    assert bool(_render_expr(note["when"], {"ansible_check_mode": False})) is False
