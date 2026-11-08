"""Contracts for exact app-agent access and credential handling."""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
VARIABLE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:token|password)[A-Za-z0-9_]*\b", re.I)


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _yaml_documents(path: Path):
    return list(yaml.safe_load_all(path.read_text(encoding="utf-8")))


def _defaults(role: str) -> dict:
    values = {}
    for path in sorted((ROOT / "roles" / role / "defaults" / "main").glob("*.yml")):
        values.update(_yaml(path) or {})
    return values


def _task_tree(tasks):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for branch in ("block", "rescue", "always"):
            yield from _task_tree(task.get(branch, []))


def _task_values(value):
    if isinstance(value, dict):
        return " ".join(_task_values(child) for child in value.values())
    if isinstance(value, list):
        return " ".join(_task_values(child) for child in value)
    return str(value) if isinstance(value, str) else ""


def test_vikunja_tiers_single_source_identity_access_and_publication():
    defaults = _defaults("vikunja")
    tiers = defaults["vikunja_agent_tiers"]
    assert {tier["id"] for tier in tiers} == {"vikunja-read", "vikunja-write"}
    assert {tier["username"] for tier in tiers} == {"svc-agent-ro", "svc-agent-rw"}
    assert all(tier["password_field"] in defaults for tier in tiers)
    assert all(tier["token_tier"] in {"read-only", "read-write"} for tier in tiers)
    assert all(tier["openbao_mount"] == "agent-tier" for tier in tiers)
    assert all(tier["openbao_path"] == tier["id"] for tier in tiers)
    assert all(tier["share_permission"] in {0, 1} for tier in tiers)
    assert all(tier["project_allowlist"] for tier in tiers)
    assert all(tier["token_field"] != "VIKUNJA_MCP_TOKEN_RW" for tier in tiers)
    assert len({tier["token_field"] for tier in tiers}) == len(tiers)

    reconcile = (ROOT / "roles/vikunja/tasks/agent_tier_reconcile.yml").read_text()
    assert "agent_revoke_direct_share.yml" in reconcile
    assert "agent_assert_parent_chain.yml" in reconcile
    assert "parent_project_id" in reconcile
    assert "api/v1/teams" in reconcile
    assert "api/v1/projects?page=" in reconcile
    assert "no_log: true" in reconcile
    assert "vikunja_agent_tier.project_allowlist" in reconcile

    access = _yaml(ROOT / "roles/vikunja/tasks/operator_access_project.yml")
    assert not any(task.get("ansible.builtin.uri", {}).get("method") == "DELETE" for task in access)


def test_vikunja_shared_leaf_publishes_only_interactive_url_and_tokens():
    defaults = _defaults("vikunja")
    assert defaults["vikunja_token_openbao_path"] == "ai/mcp/vikunja"
    publisher = (ROOT / "roles/vikunja/tasks/mcp_token_one.yml").read_text()
    assert "vikunja_mcp_token_mount" in publisher
    assert "vikunja_mcp_user.openbao_mount" in publisher
    assert "vikunja_mcp_token_static_fields" in publisher
    assert "vikunja_mcp_user.project_allowlist" in publisher
    assert "vikunja_agent_read_allowlist" not in publisher
    assert "vikunja_mcp_token_users + vikunja_openhands_token_users + vikunja_agent_tiers" in (
        ROOT / "roles/vikunja/tasks/mcp_tokens.yml"
    ).read_text()


def test_zammad_agent_write_defaults_and_exact_access_are_single_sourced():
    defaults = _defaults("zammad")
    assert defaults["zammad_agent_write_groups"] == ["{{ zammad_groups[0] }}"]
    bootstrap = (ROOT / "roles/zammad/files/zammad_bootstrap/20-groups-and-tokens.rb").read_text()
    assert "reject { |u| u.id == agent_write_user.id }" in bootstrap
    assert "JSON.parse(ENV.fetch('ZAMMAD_AGENT_WRITE_GROUPS'))" in bootstrap
    assert "%w[create change read]" in bootstrap
    assert "group_names_access_map = agent_write_access" in bootstrap
    verification = _yaml(ROOT / "roles/zammad/tasks/verify_agent_write_rights.yml")
    assert all(task.get("no_log") is True for task in verification)
    assert any(task.get("ansible.builtin.assert") for task in verification)


def test_tier_readbacks_cover_effective_permission_and_admin_refusal():
    reconcile = _yaml(ROOT / "roles/vikunja/tasks/agent_tier_reconcile.yml")
    reads = [t for t in reconcile if "/api/v1/projects/{{ item }}" in str(t.get("ansible.builtin.uri", ""))]
    assert reads and reads[0].get("no_log") is True
    checks = [t for t in reconcile if "max_permission" in str(t.get("ansible.builtin.assert", ""))]
    assert checks and "vikunja_agent_tier.share_permission" in str(checks[0])

    verify = _yaml(ROOT / "roles/zammad/tasks/verify_agent_write_rights.yml")
    probe = [t for t in verify if "zammad_agent_write_api_token" in str(t.get("ansible.builtin.uri", ""))]
    assert probe and set(probe[0]["loop"]) == {"settings", "channels_email"}
    assert any("zammad_agent_write_admin_probe" in str(t.get("ansible.builtin.assert", "")) for t in verify)


def test_every_token_or_password_variable_in_app_tasks_is_no_log():
    task_root = ROOT / "roles"
    offenders = []
    for role in ("vikunja", "zammad"):
        for path in sorted((task_root / role / "tasks").rglob("*.yml")):
            task_index = 0
            for document in _yaml_documents(path):
                for task in _task_tree(document):
                    task_index += 1
                    task_values = " ".join(
                        _task_values(value)
                        for key, value in task.items()
                        if key not in {"name", "tags"}
                    )
                    if VARIABLE.search(task_values) and task.get("no_log") is not True:
                        offenders.append(
                            f"{path.relative_to(ROOT)} task {task_index}: {task.get('name', '')}"
                        )
    assert not offenders, "token/password-bearing tasks need no_log: true: " + "; ".join(offenders)
