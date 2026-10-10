"""The AI Jobs dispatcher identity: a Vikunja user shared on one project, a token
that holds the single route creating a task, published to one field of the
open-llm bucket.

It rides the bridge tasks (hermes_bridge_identities.yml) from its own list and
its own gate. With the gate off the role never sees the identity, so nothing
is read, minted or written. The publish is a check-and-set merge: a sibling
writer's fields survive and a racing writer makes the write fail.

These render the REAL expressions out of the defaults and task files.
"""

from pathlib import Path
import re

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from vikunja_hermes_task_support import PUBLISH_TASK, ROOT, defaults, find
from secrets_collection_support import SECRETS_ROLES

ROLE = ROOT / "roles/vikunja"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, list):
        return [_trusted(item) for item in value]
    if isinstance(value, dict):
        return {key: _trusted(item) for key, item in value.items()}
    return value


def _render(value, variables: dict):
    """Render a value that may be a nested structure of templated strings."""
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(_trusted(value))


def _identity(**overrides) -> dict:
    declared = defaults()
    variables = {
        "vikunja_ai_jobs_project_id": declared["vikunja_ai_jobs_project_id"],
        "vikunja_ai_jobs_permissions": declared["vikunja_ai_jobs_permissions"],
    }
    variables.update(overrides)
    (identity,) = _render(declared["vikunja_ai_jobs_identities"], variables)
    return identity


PROBE = "Verify the stored token still authenticates for {{ vikunja_hermes_identity.username }}"
WORKS = "Record whether the stored token is usable for {{ vikunja_hermes_identity.username }}"


# --- gate: off means the identity is invisible ----------------------------------


def test_the_gate_defaults_off():
    assert defaults()["vikunja_ai_jobs_publish_openbao"] is False


def test_the_identity_is_not_in_the_hermes_list():
    names = [item["username"] for item in defaults()["vikunja_hermes_bridge_identities"]]
    assert "ai_jobs" not in names


def test_only_the_gate_puts_the_identity_in_front_of_the_bridge_tasks():
    includes = [
        task
        for task in _yaml(ROLE / "tasks/main.yml")
        if task.get("ansible.builtin.include_tasks") == "hermes_bridge_identities.yml"
    ]
    (hermes,) = [t for t in includes if "vars" not in t]
    (ai_jobs,) = [t for t in includes if "vars" in t]
    assert "vikunja_ai_jobs_publish_openbao | bool" in ai_jobs["when"]
    assert "vikunja_hermes_bridge_publish_openbao | bool" not in str(ai_jobs["when"])
    # The hermes username selector never narrows or breaks this list.
    assert ai_jobs["vars"] == {
        "vikunja_hermes_bridge_identities": "{{ vikunja_ai_jobs_identities }}",
        "vikunja_hermes_bridge_usernames": [],
    }
    assert "vikunja_ai_jobs_publish_openbao" not in str(hermes["when"])


# --- scope: one project, one route ---------------------------------------------


def test_the_token_holds_exactly_the_create_task_route():
    assert _identity()["token_permissions"] == {"tasks": ["create"]}


def test_the_token_holds_no_read_update_delete_or_project_route():
    permissions = _identity()["token_permissions"]
    assert set(permissions) == {"tasks"}
    assert not {"read_one", "read_all", "update", "delete"} & set(permissions["tasks"])


def test_the_user_is_shared_on_the_one_project_only():
    shares = _identity()["project_shares"]
    assert shares == [{"project_id": 55, "owner_username": "svc-mcp-rw", "permission": 1}]


def test_the_project_follows_one_variable():
    identity = _identity(vikunja_ai_jobs_project_id=77)
    assert [share["project_id"] for share in identity["project_shares"]] == [77]
    assert identity["probe"]["path"] == "/api/v1/projects/77/tasks"


def test_the_token_lands_in_its_own_field_of_the_open_llm_bucket():
    identity = _identity()
    assert (identity["openbao_mount"], identity["openbao_path"]) == ("secret", "apps/open-llm")
    assert identity["kv_field"] == "VIKUNJA_AI_JOBS_TOKEN"
    # The bucket's read-only token keeps its own field.
    assert identity["kv_field"] != "VIKUNJA_API_TOKEN"


def test_the_login_password_is_generated_with_the_apps_secrets():
    merged: dict = {}
    for path in sorted((SECRETS_ROLES / "openbao/defaults/main").glob("*.yml")):
        merged.update(_yaml(path) or {})
    assert f"{_identity()['username']}_login_password" in merged["openbao_generated_app_secrets"]["vikunja"]


# --- the liveness probe is the granted route ------------------------------------


def test_the_probe_is_the_create_route_with_an_empty_title():
    identity = _identity()
    probe = identity["probe"]
    assert probe["method"] == "PUT"
    assert re.fullmatch(r"/api/v1/projects/\d+/tasks", probe["path"])
    assert probe["body"] == {"title": ""}, "a probe must never create a task"
    # PUT /projects/:project/tasks is the tasks.create route.
    assert "create" in identity["token_permissions"]["tasks"]


@pytest.mark.parametrize(
    ("status", "works"),
    [(400, True), (403, True), (401, False), (200, False), (201, False), (500, False)],
)
def test_only_an_authenticated_answer_counts_as_a_working_token(status, works):
    expr = find(WORKS)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_works"]
    variables = {
        "vikunja_hermes_stored_token_check": {"status": status},
        "vikunja_hermes_identity": _identity(),
    }
    assert bool(_render(expr, variables)) is works


def test_a_probe_that_never_ran_is_not_a_working_token():
    expr = find(WORKS)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_works"]
    variables = {"vikunja_hermes_stored_token_check": {}, "vikunja_hermes_identity": _identity()}
    assert bool(_render(expr, variables)) is False


def test_the_probe_request_is_built_from_the_identity():
    request = find(PROBE)["ansible.builtin.uri"]
    variables = {
        "vikunja_port": 3456,
        "vikunja_hermes_stored_token": "tk_x",
        "vikunja_hermes_identity": _identity(),
    }
    rendered = {key: _render(request[key], variables) for key in ("url", "method", "body", "status_code")}
    assert rendered["url"] == "http://localhost:3456/api/v1/projects/55/tasks"
    assert rendered["method"] == "PUT"
    assert rendered["body"] == {"title": ""}
    assert {400, 401, 403} <= set(rendered["status_code"])


# --- identities without a probe keep the project-list probe -----------------------


def test_the_default_probe_is_unchanged_for_the_hermes_identities():
    request = find(PROBE)["ansible.builtin.uri"]
    variables = {
        "vikunja_port": 3456,
        "vikunja_hermes_stored_token": "tk_x",
        "vikunja_hermes_identity": {"username": "donna"},
    }
    assert _render(request["url"], variables) == "http://localhost:3456/api/v1/projects"
    assert _render(request["method"], variables) == "GET"
    assert sorted(_render(request["status_code"], variables)) == [200, 401, 403]
    expr = find(WORKS)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_works"]
    for status, works in ((200, True), (401, False), (403, False)):
        variables["vikunja_hermes_stored_token_check"] = {"status": status}
        assert bool(_render(expr, variables)) is works


# --- the publish is a check-and-set merge ---------------------------------------


def _publish(existing_json: dict, token="tk_new", field="VIKUNJA_AI_JOBS_TOKEN") -> dict:
    body = find(PUBLISH_TASK)["ansible.builtin.uri"]["body"]
    variables = {
        "vikunja_hermes_bao_current": {"json": existing_json},
        "vikunja_hermes_identity": {"kv_field": field},
        "vikunja_hermes_token_mint": {"json": {"token": token, "id": 9}},
    }
    return {"cas": _render(body["options"]["cas"], variables), "data": _render(body["data"], variables)}


def test_the_write_preserves_every_sibling_field():
    existing = {"data": {"data": {"UNKNOWN_SIBLING": "keep", "QDRANT_UNTRUSTED_JWT": "keep"}, "metadata": {"version": 4}}}
    result = _publish(existing)
    assert result["data"]["UNKNOWN_SIBLING"] == "keep"
    assert result["data"]["QDRANT_UNTRUSTED_JWT"] == "keep"
    assert result["data"]["VIKUNJA_AI_JOBS_TOKEN"] == "tk_new"
    assert result["data"]["VIKUNJA_AI_JOBS_TOKEN_ID"] == 9


def test_the_write_replaces_only_its_own_field():
    existing = {"data": {"data": {"VIKUNJA_API_TOKEN": "read-only", "VIKUNJA_AI_JOBS_TOKEN": "old"}, "metadata": {"version": 4}}}
    data = _publish(existing)["data"]
    assert data["VIKUNJA_API_TOKEN"] == "read-only"
    assert data["VIKUNJA_AI_JOBS_TOKEN"] == "tk_new"


def test_the_write_is_checked_against_the_version_that_was_read():
    existing = {"data": {"data": {"A": "1"}, "metadata": {"version": 4}}}
    assert _publish(existing)["cas"] == 4


def test_a_path_that_did_not_exist_is_created_with_cas_zero():
    result = _publish({"errors": []})
    assert result["cas"] == 0
    assert result["data"]["VIKUNJA_AI_JOBS_TOKEN"] == "tk_new"
    assert isinstance(result["cas"], int)
