"""The GPU fill workload's inventory values name active chat routes and pinned corpora."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = yaml.safe_load((REPO_ROOT / "roles" / "hatchet_docker" / "defaults" / "main.yml").read_text())
INVENTORY = yaml.safe_load((REPO_ROOT / "inventory" / "group_vars" / "docker_ai_group.yml").read_text())


def test_fill_roles_map_to_configured_worker_roles_and_chat_routes() -> None:
    chat_routes = {platform["name"] for platform in DEFAULTS["hatchet_docker_worker_chat_platforms"]}
    roles = INVENTORY["hatchet_docker_worker_fill_roles"]
    assert set(roles) <= set(DEFAULTS["hatchet_docker_worker_roles"])
    assert set(roles.values()) <= chat_routes


def test_fill_corpus_repos_are_unique_public_github_repos_pinned_to_tags() -> None:
    repos = INVENTORY["hatchet_docker_worker_fill_corpus_repos"]
    assert len({repo["name"] for repo in repos}) == len(repos)
    for repo in repos:
        assert repo["url"].startswith("https://github.com/dryvist/")
        assert repo["version"].startswith("v")


def test_daily_parse_eval_is_opt_in_and_fill_remains_disabled() -> None:
    assert DEFAULTS["hatchet_docker_eval_enabled"] is False
    assert INVENTORY["hatchet_docker_eval_enabled"] is False
    assert INVENTORY["hatchet_docker_eval_cron"] == "17 3 * * *"
    assert INVENTORY["hatchet_docker_eval_roles"] == [
        {"role": "small", "dataset": "vikunja-clerk-evals"}
    ]
    assert INVENTORY["hatchet_docker_worker_fill_enabled"] is False
