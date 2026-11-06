"""Validate the opt-in comparison at the worker boundary."""

import re
from urllib.parse import urlsplit


def validate(config):
    if not isinstance(config, dict) or set(config) != {
        "repos", "engines", "slack_channel", "slack_auth_env"
    }:
        raise ValueError("engineab requires repos, engines, slack_channel, slack_auth_env")
    repos = config["repos"]
    if not isinstance(repos, list) or not repos or len(set(repos)) != len(repos):
        raise ValueError("engineab repos must be a non-empty unique list")
    for repo in repos:
        if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("invalid engineab repository slug")
    engines = config["engines"]
    if not isinstance(engines, dict) or set(engines) != {"dify", "langflow", "langgraph"}:
        raise ValueError("engineab requires all three engine endpoints")
    envs = [config["slack_auth_env"]]
    for engine in engines.values():
        if not isinstance(engine, dict) or set(engine) != {"run_url", "auth_env"}:
            raise ValueError("engineab engine requires run_url and auth_env")
        url = urlsplit(engine["run_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("engineab run_url must be an HTTPS URL without credentials")
        envs.append(engine["auth_env"])
    if any(not isinstance(env, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env) for env in envs):
        raise ValueError("engineab credentials must name environment variables")
    if not isinstance(config["slack_channel"], str) or not re.fullmatch(r"[CG][A-Z0-9]+", config["slack_channel"]):
        raise ValueError("engineab slack_channel must be a channel ID")
