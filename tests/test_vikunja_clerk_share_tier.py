"""The clerk's service user gets exact direct shares through the tier reconcile, without a tier token or leaf."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jinja2 import Environment

from app_agent_helpers import _render, _yaml

ROOT = Path(__file__).resolve().parents[1]
CLERK = yaml.safe_load((ROOT / "roles/vikunja/defaults/main/16-clerk.yml").read_text(encoding="utf-8"))
ACCESS = yaml.safe_load((ROOT / "roles/vikunja/tasks/agent_read_access.yml").read_text(encoding="utf-8"))
TOKENS = (ROOT / "roles/vikunja/tasks/mcp_tokens.yml").read_text(encoding="utf-8")
VALUES = (ROOT / "roles/vikunja/tasks/read_agent_tier_values.yml").read_text(encoding="utf-8")


def test_clerk_share_tier_reuses_the_clerk_identity_and_the_dify_allowed_list():
    tier, = CLERK["vikunja_share_only_tiers"]
    assert tier["username"] == "svc-mcp-clerk"
    assert tier["share_permission"] == 1
    assert tier["password_field"] == "vikunja_clerk_share_password"
    assert tier["project_allowlist"] == "{{ vikunja_clerk_project_allowlist }}"
    assert "DIFY_VIKUNJA_CLERK_ALLOWED_PROJECTS" in CLERK["vikunja_clerk_project_allowlist"]
    assert not {"token_tier", "openbao_path", "openbao_login_path", "token_field"} & set(tier)


def test_only_the_reconcile_loop_reads_share_only_tiers():
    task = next(t for t in ACCESS if t.get("name") == "Reconcile each configured app-agent tier exactly")
    assert task["ansible.builtin.include_tasks"] == "agent_tier_reconcile.yml"
    assert "vikunja_share_only_tiers | selectattr('project_allowlist')" in task["loop"]
    assert "vikunja_share_only_tiers" not in TOKENS and "vikunja_share_only_tiers" not in VALUES


def test_an_empty_allowed_list_drops_the_tier_from_the_loop():
    env = Environment()
    loop = "{{ (tiers | selectattr('project_allowlist') | list) | length }}"
    assert env.from_string(loop).render(tiers=[{"project_allowlist": []}]) == "0"
    assert env.from_string(loop).render(tiers=[{"project_allowlist": [40]}]) == "1"


def _role_share_map(project_permissions, project_sets):
    tasks = _yaml("roles/vikunja/tasks/agent_role_share_reconcile.yml")
    build = next(task for task in tasks if task.get("name") == "Build the project ID to right map for the Vikunja agent role")
    expression = build["ansible.builtin.set_fact"]["vikunja_agent_role_share_permissions"]
    return _render(
        expression,
        {
            "vikunja_agent_role": {"project_permissions": project_permissions},
            "vikunja_agent_project_sets": project_sets,
        },
    )


def test_agent_role_maps_each_project_to_its_named_set_right():
    project_sets = {"domain": [918273], "work": [918274]}

    assert _role_share_map({"domain": 0, "work": 1}, project_sets) == {
        "918273": 0,
        "918274": 1,
    }


def test_agent_role_uses_the_higher_right_when_sets_overlap():
    project_sets = {"domain": [918275], "work": [918275]}

    assert _role_share_map({"work": 1, "domain": 0}, project_sets) == {"918275": 1}


def test_agent_role_reconcile_removes_only_its_own_direct_shares_outside_the_map():
    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    revoke_loop = next(
        task for task in reconcile if task.get("name") == "Remove the tier account's direct shares outside its allowlist"
    )
    assert "rejectattr('id', 'in', vikunja_agent_allowed_project_ids)" in revoke_loop["loop"]
    assert "vikunja_agent_tier.username" in revoke_loop["loop"]

    direct_share = _yaml("roles/vikunja/tasks/agent_revoke_direct_share.yml")
    delete = next(task for task in direct_share if task.get("name", "").startswith("Remove the tier's direct share"))
    assert "{{ vikunja_agent_tier.username | urlencode }}" in delete["ansible.builtin.uri"]["url"]


def test_empty_agent_project_set_builds_an_empty_map_without_a_nonempty_assertion():
    assert _role_share_map({"inbox": 1}, {"inbox": []}) == {}

    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    assert not any("project_allowlist | length > 0" in str(task) for task in reconcile)


def test_environment_project_sets_merge_over_the_eight_defaults(monkeypatch):
    monkeypatch.setenv("VIKUNJA_AGENT_PROJECT_SETS", json.dumps({"domain": [918276]}))
    defaults = yaml.safe_load((ROOT / "roles/vikunja/defaults/main/10-agent-tiers.yml").read_text(encoding="utf-8"))
    tasks = _yaml("roles/vikunja/tasks/agent_role_shares.yml")
    merge = next(task for task in tasks if task.get("name") == "Merge environment project IDs into the named agent project sets")
    expression = merge["ansible.builtin.set_fact"]["vikunja_agent_project_sets"]

    project_sets = _render(expression, {"vikunja_agent_project_sets": defaults["vikunja_agent_project_sets"]})

    assert set(project_sets) == {
        "domain",
        "work",
        "inbox",
        "windows",
        "jobs",
        "hermes_board",
        "donna_board",
        "acceptance",
    }
    assert project_sets["domain"] == [918276]
    assert all(project_sets[name] == [] for name in set(project_sets) - {"domain"})
    assert merge["no_log"] is True


def test_unknown_environment_project_set_fails_with_its_name(monkeypatch):
    unknown = "not_a_project_set"
    monkeypatch.setenv("VIKUNJA_AGENT_PROJECT_SETS", json.dumps({unknown: [918277]}))
    defaults = yaml.safe_load((ROOT / "roles/vikunja/defaults/main/10-agent-tiers.yml").read_text(encoding="utf-8"))
    tasks = _yaml("roles/vikunja/tasks/agent_role_shares.yml")
    merge = next(task for task in tasks if task.get("name") == "Merge environment project IDs into the named agent project sets")
    project_sets = _render(
        merge["ansible.builtin.set_fact"]["vikunja_agent_project_sets"],
        {"vikunja_agent_project_sets": defaults["vikunja_agent_project_sets"]},
    )
    reject = next(task for task in tasks if task.get("name") == "Reject unknown Vikunja agent project set names")
    condition = reject["ansible.builtin.assert"]["that"][0]

    assert _render("{{ " + condition + " }}", {"item": unknown, "vikunja_agent_project_sets": project_sets}) is False
    fail_msg = _render(reject["ansible.builtin.assert"]["fail_msg"], {"item": unknown})
    assert unknown in fail_msg
    assert tasks.index(reject) < next(
        i for i, task in enumerate(tasks) if task.get("name") == "Reconcile shares for each enabled Vikunja agent role"
    )


def test_enabled_role_reconcile_is_between_user_creation_and_mcp_tokens_and_skips_empty_enablement():
    main = yaml.safe_load((ROOT / "roles/vikunja/tasks/main.yml").read_text(encoding="utf-8"))
    names = [task.get("name") for task in main]
    users = names.index("Create Vikunja agent role users (idempotent — skipped if already present)")
    shares = names.index("Reconcile Vikunja agent role project shares")
    tokens = names.index("Validate MCP API token scopes and publish when enabled")
    reconcile = main[shares]

    assert shares == users + 1
    assert tokens == shares + 1
    assert "vikunja_agent_roles_active | length > 0" in reconcile["when"]
    assert "not ansible_check_mode" in reconcile["when"]
    defaults = yaml.safe_load((ROOT / "roles/vikunja/defaults/main/10-agent-tiers.yml").read_text(encoding="utf-8"))
    assert _render(defaults["vikunja_agent_roles_active"], defaults) == []


def test_per_project_rights_reuse_the_existing_share_requests_and_preserve_scalar_fallback():
    request = _yaml("roles/vikunja/tasks/operator_access_project.yml")
    grant = next(task for task in request if task.get("name", "").startswith("Grant the grantee a share"))
    correct = next(task for task in request if task.get("name", "").startswith("Correct the grantee's permission"))
    grant_right = grant["ansible.builtin.uri"]["body"]["permission"]
    correct_right = correct["ansible.builtin.uri"]["body"]["permission"]

    assert "vikunja_share_project_permission_map" in grant_right
    assert "vikunja_share_permission" in grant_right
    assert "vikunja_share_project_permission_map" in correct_right
    assert "vikunja_share_permission" in correct_right
    reconcile = _yaml("roles/vikunja/tasks/agent_tier_reconcile.yml")
    assert any(task.get("when") == "vikunja_agent_tier.project_permission_map is not defined" for task in reconcile)
    assert any(task.get("name") == "Assert the tier account holds each configured per-project permission" for task in reconcile)
