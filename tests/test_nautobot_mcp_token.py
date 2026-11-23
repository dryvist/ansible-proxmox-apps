"""The Nautobot MCP token is published by inventory and can never write."""

import ast
from pathlib import Path

import yaml

from app_agent_helpers import _render, _task

ROOT = Path(__file__).resolve().parents[1]


def _assignments(tree):
    return {
        (ast.unparse(target), ast.unparse(node.value))
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
    }


def test_inventory_enables_the_nautobot_mcp_token_publisher():
    group_vars = yaml.safe_load((ROOT / "inventory/group_vars/nautobot_group.yml").read_text(encoding="utf-8"))
    assert group_vars["nautobot_mcp_token_publish_openbao"] is True


def test_nautobot_mcp_token_is_created_and_kept_write_disabled():
    tree = ast.parse((ROOT / "roles/nautobot/files/mcp_token_bootstrap.py").read_text(encoding="utf-8"))
    token_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "Token"]
    assert token_calls
    for call in token_calls:
        assert any(
            keyword.arg == "write_enabled" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            for keyword in call.keywords
        )
    assignments = _assignments(tree)
    assert {value for target, value in assignments if target == "token.write_enabled"} == {"False"}
    assert ("user.is_superuser", "False") in assignments
    assert ("user.is_staff", "False") in assignments
    assert {value for target, value in assignments if target == "perm.actions"} == {"['view']"}


def test_check_mode_reads_the_leaf_reports_missing_keys_and_writes_nothing():
    tasks = yaml.safe_load((ROOT / "roles/nautobot/tasks/mcp_token.yml").read_text(encoding="utf-8"))
    assert _task(tasks, "Ensure the read-only MCP token exists")["no_log"] is True
    assert _task(tasks, "Extract the read-only token from the bootstrap output")["when"] == "not ansible_check_mode"
    read = _task(tasks, "Read current OpenBao secret at {{ nautobot_mcp_token_openbao_path }}")
    assert read["ansible.builtin.uri"]["method"] == "GET"
    assert read["check_mode"] is False
    assert _task(tasks, "Publish the read-only MCP connection to OpenBao")["when"][0] == "not ansible_check_mode"

    report = _task(tasks, "Report the MCP connection keys a real run would publish")
    assert report["when"] == "ansible_check_mode"
    assert "no_log" not in report
    defaults = yaml.safe_load((ROOT / "roles/nautobot/defaults/main/00-core.yml").read_text(encoding="utf-8"))
    names = {key: defaults[key] for key in defaults if key.startswith("nautobot_mcp_token_openbao_")}
    leaf = {"NAUTOBOT_MCP_URL": "https://fixture.example", "OTHER": "fixture-secret-sibling-value"}
    shown = _render(report["ansible.builtin.debug"]["msg"], {**names, "nautobot_mcp_bao_data": leaf})
    assert shown == "ai/mcp/nautobot lacks: ['NAUTOBOT_MCP_TOKEN']"
    full = {**leaf, "NAUTOBOT_MCP_TOKEN": "fixture-secret-token-value"}
    assert _render(report["ansible.builtin.debug"]["msg"], {**names, "nautobot_mcp_bao_data": full}) == (
        "ai/mcp/nautobot lacks: []"
    )
