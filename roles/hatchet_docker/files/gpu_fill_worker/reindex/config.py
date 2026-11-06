"""Validate opt-in reindex configuration before registering any job."""

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def validate(config):
    if not isinstance(config, dict) or set(config) != {
        "repos", "hindsight_export", "hindsight_collection", "router_url", "qdrant_url",
        "output_dir", "smoke_query",
    }:
        raise ValueError("invalid reindex configuration fields")
    for key in ("router_url", "qdrant_url"):
        if not isinstance(config[key], str):
            raise ValueError(f"reindex {key} must be a URL")
        parsed = urlsplit(config[key])
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError(f"reindex {key} must be an HTTP(S) base URL without credentials")
    if not isinstance(config["repos"], list):
        raise ValueError("reindex repos must be a list")
    seen = set()
    for repo in config["repos"]:
        if not isinstance(repo, dict) or set(repo) != {"url", "collection"}:
            raise ValueError("reindex repo requires url and collection")
        if not isinstance(repo["url"], str):
            raise ValueError("reindex repo URL must be a string")
        parsed = urlsplit(repo["url"])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.port not in {None, 443}
                or "." not in parsed.hostname or parsed.hostname.endswith((".local", ".internal"))):
            raise ValueError("reindex repo requires a public HTTPS URL without credentials")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("reindex repo requires a public HTTPS URL")
        if repo["url"] in seen:
            raise ValueError("duplicate reindex repo URL")
        seen.add(repo["url"])
        if not isinstance(repo["collection"], str) or not _NAME.fullmatch(repo["collection"]):
            raise ValueError("invalid reindex collection")
    if not isinstance(config["hindsight_export"], str) or (
        config["hindsight_export"] and not Path(config["hindsight_export"]).is_absolute()
    ):
        raise ValueError("reindex hindsight_export must be empty or an absolute path")
    if (not isinstance(config["hindsight_collection"], str)
            or not _NAME.fullmatch(config["hindsight_collection"])):
        raise ValueError("invalid reindex hindsight_collection")
    if not config["repos"] and not config["hindsight_export"]:
        raise ValueError("reindex requires at least one source")
    if not isinstance(config["output_dir"], str) or not Path(config["output_dir"]).is_absolute():
        raise ValueError("reindex output_dir must be an absolute path")
    if not isinstance(config["smoke_query"], str):
        raise ValueError("reindex smoke_query must be a string")
