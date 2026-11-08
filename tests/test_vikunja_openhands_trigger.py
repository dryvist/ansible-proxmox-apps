"""The OpenHands trigger bot: the openhands service user, the hand-created
trigger project shared with it, its own status labels, and one API token
scoped to commenting and label swaps, published to the app's own OpenBao
bucket.

The trigger project and the `openhands` trigger label are created by hand
under the operator's account, never by this role — the role receives the
project by id, shares it at the lowest write permission, and pre-creates the
status labels as the bot user (looked up by title, created only when absent).
The token row rides tasks/mcp_tokens.yml beside the shared MCP rows.

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
TRIGGER = "roles/vikunja/tasks/openhands_trigger.yml"
MCP_TOKENS = "roles/vikunja/tasks/mcp_tokens.yml"
MCP_TOKEN_ONE = "roles/vikunja/tasks/mcp_token_one.yml"

SHARE = "Share the OpenHands trigger project with the openhands bot"
NO_PROJECT_NOTE = "Note the OpenHands trigger project share is skipped without a project id"
NO_USER_NOTE = "Note the OpenHands service user is not provisioned"
LABELS_READ = "Read the openhands bot's existing labels"
LABELS_CREATE = "Create the openhands status labels that are absent"
READBACK = "Read the trigger project as the openhands bot"
MCP_LOOP = "Mint and publish MCP and app-agent tokens per identity"
RESOLVE = "Resolve token title, permissions, and OpenBao target for {{ vikunja_mcp_user.username }}"
LOGIN = "Log in to Vikunja as {{ vikunja_mcp_user.username }}"


def _yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def defaults():
    merged = {}
    for path in sorted(DEFAULTS_DIR.glob("*.yml")):
        merged.update(_yaml(path) or {})
    return merged


def find(name, rel):
    for task in _yaml(ROOT / rel):
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {rel}")


def _trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, list):
        return [_trusted(item) for item in value]
    if isinstance(value, dict):
        return {key: _trusted(item) for key, item in value.items()}
    return value


def _render(value, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(_trusted(value))


def _render_expr(condition, variables):
    """Render a bare `when` condition: the source is not wrapped in {{ }}."""
    return _render("{{ " + condition + " }}", variables)


def _row():
    (row,) = defaults()["vikunja_openhands_token_users"]
    return row


def _share_when(project_id, *, check_mode=False, password="pw", operator="jevans", owner_map=None):
    variables = {
        "ansible_check_mode": check_mode,
        "vikunja_openhands_project_id": project_id,
        "vikunja_openhands_user": {"password": password},
        "vikunja_operator_username": operator,
        "vikunja_project_share_owner_password_map": (
            {"jevans": "pw"} if owner_map is None else owner_map
        ),
    }
    task = find(SHARE, TRIGGER)
    return all(bool(_render_expr(condition, variables)) for condition in task["when"])


# --- defaults: one variable per decision ---------------------------------------


def test_the_trigger_project_is_matched_by_id_with_the_hand_made_default():
    assert defaults()["vikunja_openhands_project_id"] == 90


def test_the_share_permission_is_write_the_lowest_that_can_comment_and_label():
    assert defaults()["vikunja_openhands_permission"] == 1


def test_the_status_labels_are_exactly_the_three_trigger_states():
    assert defaults()["vikunja_openhands_labels"] == [
        "openhands-running",
        "openhands-done",
        "openhands-failed",
    ]


def test_the_token_holds_exactly_the_trigger_surface():
    assert defaults()["vikunja_openhands_permissions"] == {
        "labels": ["read_all"],
        "projects": ["read_all"],
        "tasks": ["read_all", "read_one"],
        "tasks_comments": ["create"],
        "tasks_labels": ["create", "delete"],
    }


def test_the_token_route_groups_are_the_roles_established_names():
    scopes = set(defaults()["vikunja_mcp_token_scopes"])
    assert set(defaults()["vikunja_openhands_permissions"]) <= scopes


def test_the_token_actions_stay_inside_vikunjas_standard_vocabulary():
    actions = set()
    for group_actions in defaults()["vikunja_openhands_permissions"].values():
        actions |= set(group_actions)
    assert actions <= {"read_all", "read_one", "create", "update", "delete"}


# --- the token row rides the existing mint-and-publish mechanism ---------------


def test_the_token_row_targets_its_own_app_bucket_with_the_token_field():
    row = _row()
    assert row["username"] == "openhands"
    assert row["title"] == "openhands-trigger"
    assert (row["openbao_mount"], row["openbao_path"]) == ("secret", "apps/openhands-vikunja")
    assert row["kv_fields"] == ["token"]


def test_the_token_row_is_never_published_to_the_shared_vikunja_path():
    row = _row()
    assert (row["openbao_mount"], row["openbao_path"]) != (
        defaults()["vikunja_token_openbao_mount"],
        defaults()["vikunja_token_openbao_path"],
    )


def test_the_token_row_joins_the_existing_mint_loop():
    loop = _render(find(MCP_LOOP, MCP_TOKENS)["loop"], defaults())
    assert loop == (
        defaults()["vikunja_mcp_token_users"]
        + defaults()["vikunja_openhands_token_users"]
        + defaults()["vikunja_agent_tiers"]
    )
    usernames = [entry["username"] for entry in loop]
    assert usernames.count("openhands") == 1


def test_the_row_resolves_to_its_own_title_permissions_and_bucket():
    variables = dict(defaults())
    # Nested template strings only render when trusted, like Ansible's own
    # trust model — mark the row before handing it to the Templar.
    variables["vikunja_mcp_user"] = _trusted(_row())
    # A set_fact map's later keys see the earlier keys' results — thread them
    # the same way Ansible's lazy templating does.
    resolved = {}
    for key, expression in find(RESOLVE, MCP_TOKEN_ONE)["ansible.builtin.set_fact"].items():
        resolved[key] = _render(expression, {**variables, **resolved})
    assert resolved["vikunja_mcp_token_title"] == "openhands-trigger"
    assert resolved["vikunja_mcp_token_mount"] == "secret"
    assert resolved["vikunja_mcp_token_path"] == "apps/openhands-vikunja"
    assert resolved["vikunja_mcp_token_fields"] == ["token"]
    assert resolved["vikunja_mcp_token_permissions"] == defaults()["vikunja_openhands_permissions"]


def test_the_app_bucket_never_receives_the_shared_url_or_allowlist_fields():
    static = find(RESOLVE, MCP_TOKEN_ONE)["ansible.builtin.set_fact"]["vikunja_mcp_token_static_fields"]
    variables = {
        "vikunja_mcp_user": _row(),
        "vikunja_mcp_token_mount": "secret",
        "vikunja_mcp_token_path": "apps/openhands-vikunja",
        "vikunja_token_openbao_mount": defaults()["vikunja_token_openbao_mount"],
        "vikunja_token_openbao_path": defaults()["vikunja_token_openbao_path"],
        "vikunja_url_openbao_key": "VIKUNJA_MCP_URL",
        "vikunja_mcp_url": "https://vikunja.example/api/v1",
    }
    assert _render(static, variables) == {}


def test_the_mint_logs_in_with_the_service_users_password(monkeypatch):
    login = find(LOGIN, MCP_TOKEN_ONE)["ansible.builtin.uri"]["body"]["password"]
    # The token row declares no password_field, so the login resolves the
    # openhands row out of vikunja_service_users — the same list the
    # service-user creation task reads. The row's password is itself a
    # template (the injection-agnostic env lookup), so run it with the env
    # set; trust the strings like Ansible does before handing them over.
    monkeypatch.setenv("VIKUNJA_OPENHANDS_PASSWORD", "pw-openhands")
    variables = {
        "vikunja_mcp_user": _trusted(_row()),
        "vikunja_service_users": _trusted(defaults()["vikunja_service_users"]),
    }
    assert _render(login, variables) == "pw-openhands"


# --- the service user ----------------------------------------------------------


def test_openhands_is_a_declared_service_user_with_an_empty_default_password():
    users = [user for user in defaults()["vikunja_service_users"] if user["username"] == "openhands"]
    (user,) = users
    assert user["password"] == "{{ lookup('env', 'VIKUNJA_OPENHANDS_PASSWORD') }}"


def test_the_group_vars_password_is_bao_first_and_fails_closed():
    group_vars = _yaml(ROOT / "inventory/group_vars/vikunja_group.yml")
    (user,) = [u for u in group_vars["vikunja_service_users"] if u["username"] == "openhands"]
    variables = {"bao_apps_secrets": {"openhands_login_password": "pw-from-bao"}}
    assert _render(user["password"], variables) == "pw-from-bao"
    with pytest.raises(Exception):
        _render(user["password"], {"bao_apps_secrets": {}})


# --- the share: one owner, one project, one skip note --------------------------


def test_the_share_reuses_the_shared_reconciler():
    assert find(SHARE, TRIGGER)["ansible.builtin.include_tasks"] == "operator_access_one.yml"


def test_the_share_loop_targets_the_operator_account():
    loop = find(SHARE, TRIGGER)["loop"]
    assert _render(loop, {"vikunja_operator_username": "jevans"}) == ["jevans"]


def test_the_share_drives_the_reconciler_with_the_trigger_triple():
    variables = {
        "vikunja_openhands_project_id": 90,
        "vikunja_openhands_permission": 1,
    }
    rendered = {
        key: _render(value, variables) for key, value in find(SHARE, TRIGGER)["vars"].items()
    }
    assert rendered["vikunja_share_grantee_username"] == "openhands"
    assert rendered["vikunja_share_permission"] == 1
    assert rendered["vikunja_share_project_ids"] == [90]


def test_the_share_runs_when_the_project_and_credentials_are_set():
    assert _share_when(90) is True


def test_the_share_follows_the_configured_project_id():
    assert _share_when(77) is True


def test_an_empty_project_id_skips_the_share():
    assert _share_when("") is False


def test_the_share_skips_in_check_mode():
    assert _share_when(90, check_mode=True) is False


def test_the_share_skips_without_a_provisioned_bot_password():
    assert _share_when(90, password="") is False


def test_the_share_skips_without_an_owner_credential():
    assert _share_when(90, owner_map={}) is False


def test_the_skip_is_announced_by_its_task_name_and_condition():
    note = find(NO_PROJECT_NOTE, TRIGGER)
    assert "skipped" in note["name"]
    variables = {"vikunja_openhands_project_id": ""}
    assert bool(_render_expr(note["when"], variables)) is True
    variables["vikunja_openhands_project_id"] = 90
    assert bool(_render_expr(note["when"], variables)) is False


def test_a_missing_service_user_is_announced_by_its_task_name():
    note = find(NO_USER_NOTE, TRIGGER)
    assert "not provisioned" in note["name"]
    variables = {"vikunja_openhands_user": {}}
    assert bool(_render_expr(note["when"], variables)) is True
    variables["vikunja_openhands_user"] = {"password": "pw"}
    assert bool(_render_expr(note["when"], variables)) is False


# --- the status labels: as the bot, by title, create-only-when-absent ----------


def test_labels_are_read_from_the_bots_own_session():
    task = find(LABELS_READ, TRIGGER)["ansible.builtin.uri"]
    variables = {
        "vikunja_port": 8080,
        "vikunja_openhands_login": {"json": {"token": "jwt"}},
    }
    assert _render(task["url"], variables) == "http://localhost:8080/api/v1/labels"
    assert task["method"] == "GET"
    assert _render(task["headers"]["Authorization"], variables) == "Bearer jwt"


def test_labels_are_matched_by_title_and_created_only_when_absent():
    when = find(LABELS_CREATE, TRIGGER)["when"]
    variables = {
        "ansible_check_mode": False,
        "vikunja_openhands_user": {"password": "pw"},
        "vikunja_openhands_labels_current": {
            "json": [{"title": "openhands-running"}],
        },
    }
    assert _render_expr(when[2], {**variables, "item": "openhands-running"}) is False
    assert _render_expr(when[2], {**variables, "item": "openhands-done"}) is True
    assert _render_expr(when[2], {**variables, "item": "openhands-failed"}) is True


def test_absent_labels_are_created_by_title_through_the_labels_route():
    task = find(LABELS_CREATE, TRIGGER)["ansible.builtin.uri"]
    variables = {
        "vikunja_port": 8080,
        "item": "openhands-done",
        "vikunja_openhands_login": {"json": {"token": "jwt"}},
    }
    assert _render(task["url"], variables) == "http://localhost:8080/api/v1/labels"
    assert task["method"] == "PUT"
    assert task["body"] == {"title": "{{ item }}"}
    assert _render(task["headers"]["Authorization"], variables) == "Bearer jwt"
    assert find(LABELS_CREATE, TRIGGER)["loop"] == "{{ vikunja_openhands_labels }}"


def test_the_label_loop_covers_exactly_the_three_status_labels():
    loop = _render(find(LABELS_CREATE, TRIGGER)["loop"], defaults())
    assert loop == defaults()["vikunja_openhands_labels"]


# --- the readback proves effective visibility ----------------------------------


def test_the_share_is_read_back_as_the_bot_on_the_trigger_project():
    task = find(READBACK, TRIGGER)["ansible.builtin.uri"]
    variables = {
        "vikunja_port": 8080,
        "vikunja_openhands_project_id": 90,
        "vikunja_openhands_login": {"json": {"token": "jwt"}},
    }
    assert _render(task["url"], variables) == "http://localhost:8080/api/v1/projects/90"
    assert task["method"] == "GET"
    assert task["status_code"] == [200]


# --- wiring in main.yml --------------------------------------------------------


def test_the_trigger_include_sits_before_the_token_validation():
    names = [task.get("name") for task in _yaml(ROOT / MAIN)]
    assert names.index("Provision the OpenHands trigger bot") < names.index(
        "Validate MCP API token scopes and publish when enabled"
    )


def test_the_trigger_include_points_at_the_trigger_task_file():
    include = find("Provision the OpenHands trigger bot", MAIN)
    assert include["ansible.builtin.include_tasks"] == "openhands_trigger.yml"
    assert include["no_log"] is True
