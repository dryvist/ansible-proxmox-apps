"""Zammad's AI provider authenticates with its own scoped router key, never
the shared router master key.

zammad_ai_provider_token (inventory/group_vars/zammad_group.yml, the value
that actually reaches the converge — role defaults are the molecule/dry-run
fallback) used to read bao_local_llm_secrets.LLM_ROUTER_MASTER_KEY directly.
It now reads bao_apps_secrets.zammad_llm_router_key, mandatory.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GROUP_VARS = (REPO_ROOT / "inventory" / "group_vars" / "zammad_group.yml").read_text()
ROLE_DEFAULTS = (REPO_ROOT / "roles" / "zammad" / "defaults" / "main" / "00-install-db-ai.yml").read_text()


def test_group_vars_reads_its_own_scoped_router_key() -> None:
    assert "bao_apps_secrets.zammad_llm_router_key" in GROUP_VARS


def test_group_vars_no_longer_reads_the_shared_master_key() -> None:
    assert "LLM_ROUTER_MASTER_KEY" not in GROUP_VARS


def test_group_vars_token_is_mandatory() -> None:
    token_idx = GROUP_VARS.index("zammad_ai_provider_token:")
    token_block = GROUP_VARS[token_idx : token_idx + 300]
    assert "mandatory(" in token_block


def test_role_default_fallback_no_longer_names_the_shared_master_key() -> None:
    assert "LLM_ROUTER_MASTER_KEY" not in ROLE_DEFAULTS
