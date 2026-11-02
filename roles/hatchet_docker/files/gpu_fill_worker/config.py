"""Read and validate the worker's JSON configuration without SDK imports."""

import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _require_name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty identifier")


def _require_cron(value, label):
    if not isinstance(value, str) or (value and not value.strip()):
        raise ValueError(f"{label} must be an empty string or a five-field cron expression")
    if value and len(value.split()) != 5:
        raise ValueError(f"{label} must be an empty string or a five-field cron expression")


def load_config(path):
    """Load a worker config file and reject malformed role, platform, or eval data."""
    with Path(path).open(encoding="utf-8") as config_file:
        config = json.load(config_file)

    if (
        not isinstance(config, dict)
        or not {"roles", "platforms"}.issubset(config)
        or set(config) - {"roles", "platforms", "latency_guard", "evals"}
    ):
        raise ValueError("config must contain roles and platforms with optional latency_guard and evals")

    roles = config["roles"]
    platforms = config["platforms"]
    if not isinstance(roles, dict) or not roles:
        raise ValueError("roles must be a non-empty object")
    if not isinstance(platforms, dict) or not platforms:
        raise ValueError("platforms must be a non-empty object")

    for name, role in roles.items():
        _require_name(name, "role name")
        if not isinstance(role, dict) or set(role) != {"max_runs"}:
            raise ValueError(f"role {name} must contain max_runs only")
        max_runs = role["max_runs"]
        if type(max_runs) is not int or max_runs < 1:
            raise ValueError(f"role {name} max_runs must be a positive integer")

    for name, platform in platforms.items():
        _require_name(name, "platform name")
        if not isinstance(platform, dict) or set(platform) != {
            "run_url",
            "auth_env",
            "timeout_s",
        }:
            raise ValueError(f"platform {name} has invalid fields")
        run_url = platform["run_url"]
        parsed_url = urlsplit(run_url) if isinstance(run_url, str) else None
        if (
            parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError(f"platform {name} run_url must be an absolute HTTP(S) URL")
        auth_env = platform["auth_env"]
        if auth_env is not None and (
            not isinstance(auth_env, str) or not _ENV_NAME.fullmatch(auth_env)
        ):
            raise ValueError(f"platform {name} auth_env must be null or an env var name")
        timeout_s = platform["timeout_s"]
        if type(timeout_s) is not int or timeout_s < 1:
            raise ValueError(f"platform {name} timeout_s must be a positive integer")

    if "latency_guard" in config:
        guard = config["latency_guard"]
        if not isinstance(guard, dict) or set(guard) != {
            "prometheus_url",
            "query",
            "max_ratio",
        }:
            raise ValueError("latency_guard must contain prometheus_url, query, and max_ratio only")
        prometheus_url = guard["prometheus_url"]
        parsed_url = urlsplit(prometheus_url) if isinstance(prometheus_url, str) else None
        if (
            parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError("latency_guard prometheus_url must be an absolute HTTP(S) URL")
        if not isinstance(guard["query"], str) or not guard["query"].strip():
            raise ValueError("latency_guard query must be a non-empty string")
        max_ratio = guard["max_ratio"]
        if (
            type(max_ratio) not in {int, float}
            or not math.isfinite(max_ratio)
            or max_ratio <= 0
        ):
            raise ValueError("latency_guard max_ratio must be a finite positive number")

    if "evals" in config:
        evals = config["evals"]
        if not isinstance(evals, dict) or set(evals) != {
            "cron",
            "judges_sync_cron",
            "prompts_dir",
            "roles",
        }:
            raise ValueError("evals must contain cron, judges_sync_cron, prompts_dir, and roles only")
        _require_cron(evals["cron"], "evals cron")
        _require_cron(evals["judges_sync_cron"], "evals judges_sync_cron")
        prompts_dir = evals["prompts_dir"]
        if not isinstance(prompts_dir, str) or not Path(prompts_dir).is_absolute():
            raise ValueError("evals prompts_dir must be an absolute path")
        eval_roles = evals["roles"]
        if not isinstance(eval_roles, list) or not eval_roles:
            raise ValueError("evals roles must be a non-empty list")
        seen_roles = set()
        for eval_role in eval_roles:
            if not isinstance(eval_role, dict) or set(eval_role) != {"role", "dataset"}:
                raise ValueError("each eval role must contain role and dataset only")
            _require_name(eval_role["role"], "eval role")
            _require_name(eval_role["dataset"], "eval dataset")
            if eval_role["role"] in seen_roles:
                raise ValueError(f"duplicate eval role: {eval_role['role']}")
            seen_roles.add(eval_role["role"])

    return config
