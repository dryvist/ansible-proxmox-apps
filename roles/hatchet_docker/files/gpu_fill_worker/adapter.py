"""Synchronous HTTP adapter for one platform agent run."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _http_post(url, body, headers, timeout_s):
    request = Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except HTTPError as response:
        return response.code, response.read()


def run_agent(platform_cfg, payload, http_post=None):
    """POST one JSON payload and return the platform's JSON object response."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    auth_env = platform_cfg["auth_env"]
    if auth_env is not None:
        token = os.environ.get(auth_env)
        if not token:
            raise ValueError(f"required platform credential {auth_env} is empty")
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(payload).encode("utf-8")
    status, response_body = (http_post or _http_post)(
        platform_cfg["run_url"], body, headers, platform_cfg["timeout_s"]
    )
    if not 200 <= status < 300:
        raise RuntimeError(f"platform run API returned HTTP {status}")

    result = json.loads(response_body) if response_body else {}
    if not isinstance(result, dict):
        raise ValueError("platform run API response must be a JSON object")
    return result
