"""The Hermes vikunja-clerk tier holds exactly the contract token scope."""

from app_agent_helpers import _render, _vikunja_defaults


def test_vikunja_hermes_clerk_tier_has_the_contract_token_scope():
    defaults = _vikunja_defaults()
    row = next(row for row in defaults["vikunja_agent_tiers"] if row["id"] == "vikunja-clerk")
    assert row["permissions"] == "{{ vikunja_hermes_clerk_permissions }}"
    assert row["username"] != "svc-mcp-clerk"
    permissions = _render(defaults["vikunja_hermes_clerk_permissions"], defaults)
    assert permissions == {
        "labels": ["read_all"],
        "projects": ["read_all"],
        "tasks": ["create", "read_all", "read_one", "update"],
        "tasks_comments": ["create", "read_all"],
        "tasks_labels": ["create"],
        "tasks_relations": ["create"],
    }
    assert not any(action.startswith("delete") for actions in permissions.values() for action in actions)
    paths = [tier["openbao_path"] for tier in defaults["vikunja_agent_tiers"]]
    assert len(set(paths)) == len(paths)
