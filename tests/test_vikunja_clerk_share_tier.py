"""The clerk's service user gets exact direct shares through the tier reconcile, without a tier token or leaf."""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment

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
