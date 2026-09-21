"""n8n's LiteLLM Request node authenticates with its own scoped router key,
never a shared broader credential.

n8n_docker_llm_api_key used to read ai_orchestration_model_api_key (the
router's shared master key) directly. It now reads its own
n8n_llm_router_key from bao_apps_secrets, mandatory — an unseeded value
fails the converge loudly instead of silently falling back.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = (REPO_ROOT / "roles" / "n8n_docker" / "defaults" / "main.yml").read_text()


def test_llm_api_key_reads_its_own_scoped_router_key() -> None:
    assert "bao_apps_secrets['n8n_llm_router_key']" in DEFAULTS


def test_llm_api_key_no_longer_falls_back_to_the_shared_master_key() -> None:
    assert "ai_orchestration_model_api_key" not in DEFAULTS


def test_llm_api_key_is_mandatory() -> None:
    key_line_start = DEFAULTS.index("n8n_docker_llm_api_key:")
    key_block = DEFAULTS[key_line_start : key_line_start + 300]
    assert "mandatory(" in key_block
