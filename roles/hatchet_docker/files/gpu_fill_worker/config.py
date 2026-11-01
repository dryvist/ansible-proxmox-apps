"""Read and validate the worker's JSON configuration without SDK imports."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _require_name(value, label):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty identifier")


def load_config(path):
    """Load a worker config file and reject malformed role or platform data."""
    with Path(path).open(encoding="utf-8") as config_file:
        config = json.load(config_file)

    if not isinstance(config, dict) or set(config) != {"roles", "platforms"}:
        raise ValueError("config must contain exactly roles and platforms")

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

    return config
