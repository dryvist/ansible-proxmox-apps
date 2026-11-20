"""The Nautobot MCP token is published by inventory and can never write."""

import ast
from pathlib import Path

import yaml

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
