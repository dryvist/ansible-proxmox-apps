"""The platform env prefetch keeps only its declared credential settings."""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks" / "site" / "00-load-and-telemetry.yml"
TASK_NAME = (
    "Keep AppRole pairs, their source-address binds and "
    "GitHub App installation settings"
)


def test_platform_env_filter_keeps_only_approles_binds_and_github_settings():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    task = next(
        task
        for play in plays
        for task in play.get("tasks", [])
        if task.get("name") == TASK_NAME
    )
    kept_keys_pattern = task["vars"]["_kept_keys"]

    platform_env = {
        key: key
        for key in (
            "OPENBAO_APPROLE_X_ROLE_ID",
            "OPENBAO_APPROLE_X_SECRET_ID",
            "OPENBAO_OPENHANDS_SECRET_ID_CIDR",
            "OPENBAO_APPROLE_X_SECRET_ID_CIDR",
            "OPENBAO_DIFY_AGENT_CIDR",
            "OPENBAO_SANDBOX_AGENT_CIDRS",
            "OPENBAO_GITHUB_FOO_INSTALLATION_ID",
            "OPENBAO_CIDR",
            "OPENBAO_APPROLE_ALLOW_UNBOUND_CIDRS",
            "OPENBAO_DIFY_AGENT_CIDR\n",
            "SOME_OTHER_SECRET",
            "OPENBAO_SOMETHING_ELSE",
            "OPENBAO_OPENHANDS_SECRET_ID_CIDR_EXTRA",
        )
    }
    kept = {
        key
        for key in platform_env
        if re.match(kept_keys_pattern, key)
    }

    assert kept == {
        "OPENBAO_APPROLE_X_ROLE_ID",
        "OPENBAO_APPROLE_X_SECRET_ID",
        "OPENBAO_OPENHANDS_SECRET_ID_CIDR",
        "OPENBAO_APPROLE_X_SECRET_ID_CIDR",
        "OPENBAO_DIFY_AGENT_CIDR",
        "OPENBAO_SANDBOX_AGENT_CIDRS",
        "OPENBAO_GITHUB_FOO_INSTALLATION_ID",
    }
