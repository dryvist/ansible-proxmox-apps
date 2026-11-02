"""Synchronous HTTP adapter for one platform agent run."""

import json
import math
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
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


def _http_get(url, timeout_s):
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except HTTPError as response:
        return response.code, response.read()


class LatencyGuardError(RuntimeError):
    """The latency guard blocked dispatch or could not be checked safely."""


def _check_latency_guard(guard, timeout_s, http_get=None):
    query_url = (
        guard["prometheus_url"].rstrip("/")
        + "/api/v1/query?"
        + urlencode({"query": guard["query"]})
    )
    try:
        status, response_body = (http_get or _http_get)(query_url, timeout_s)
        if not 200 <= status < 300:
            raise ValueError(f"Prometheus returned HTTP {status}")
        response = json.loads(response_body)
        if not isinstance(response, dict) or response.get("status") != "success":
            raise ValueError("Prometheus query did not succeed")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ValueError("Prometheus query response has no data object")

        if data.get("resultType") == "scalar":
            result = data.get("result")
            if not isinstance(result, list) or len(result) != 2:
                raise ValueError("Prometheus scalar result is malformed")
            values = [result[1]]
        elif data.get("resultType") == "vector":
            result = data.get("result")
            if not isinstance(result, list):
                raise ValueError("Prometheus vector result is malformed")
            values = [sample["value"][1] for sample in result]
        else:
            raise ValueError("Prometheus query returned an unsupported result type")

        for value in values:
            ratio = float(value)
            if not math.isnan(ratio) and ratio > guard["max_ratio"]:
                raise LatencyGuardError(
                    f"interactive latency ratio {ratio:g} exceeds {guard['max_ratio']:g}"
                )
    except LatencyGuardError:
        raise
    except Exception as exc:
        raise LatencyGuardError("latency guard query failed; refusing GPU-fill dispatch") from exc


def run_agent(platform_cfg, payload, http_post=None, latency_guard=None, http_get=None):
    """POST one JSON payload and return the platform's JSON object response."""
    if latency_guard is not None:
        _check_latency_guard(latency_guard, platform_cfg["timeout_s"], http_get)

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
