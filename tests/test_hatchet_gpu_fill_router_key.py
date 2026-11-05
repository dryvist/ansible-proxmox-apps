"""The GPU fill chat platforms read the router key the apps prefetch provides.

The key is the apps/gpu-fill field gpu_fill_llm_router_key, merged flat into
bao_apps_secrets. Each chat platform names that field in auth_secret_key, and the
compose template reads it from bao_apps_secrets, mandatory. The single emitted
GPU_FILL_ROUTER_API_KEY line is covered by tests/hatchet_gpu_fill_worker/render_fill_templates.yml.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_TEXT = (REPO_ROOT / "roles" / "hatchet_docker" / "defaults" / "main.yml").read_text()
DEFAULTS = yaml.safe_load(DEFAULTS_TEXT)
COMPOSE = (REPO_ROOT / "roles" / "hatchet_docker" / "templates" / "docker-compose.yml.j2").read_text()


def test_chat_platforms_read_the_apps_router_key_field() -> None:
    platforms = DEFAULTS["hatchet_docker_worker_chat_platforms"]
    assert {platform["auth_secret_key"] for platform in platforms} == {"gpu_fill_llm_router_key"}


def test_retired_router_key_name_is_not_referenced() -> None:
    assert "hatchet_gpu_fill_router_api_key" not in DEFAULTS_TEXT


def test_compose_reads_the_platform_secret_from_bao_apps_secrets_mandatory() -> None:
    start = COMPOSE.index("bao_apps_secrets[worker_platform.auth_secret_key]")
    assert "mandatory(" in COMPOSE[start : start + 400]
