"""Small authenticated client for the Vikunja API v2 routes used by triage."""

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PAGE_SIZE = 50


def _http_request(url, headers, method, body, timeout_s):
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except HTTPError as response:
        return response.code, response.read()


class VikunjaClient:
    """Use one token from the configured environment variable; never log it."""

    def __init__(self, api_url, auth_env, request_fn=None, timeout_s=30):
        token = os.environ.get(auth_env)
        if not token:
            raise ValueError(f"required Vikunja credential {auth_env} is empty")
        self.api_url = api_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        self.request_fn = request_fn or _http_request
        self.timeout_s = timeout_s

    def _call(self, method, path, params=None, payload=None):
        url = self.api_url + path
        if params:
            url += "?" + urlencode(params)
        body = None
        headers = dict(self.headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        status, response_body = self.request_fn(
            url, headers, method, body, self.timeout_s
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"Vikunja API returned HTTP {status} for {method}")
        try:
            result = json.loads(response_body) if response_body else None
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Vikunja API returned invalid JSON") from exc
        return result

    def _list(self, path, params=None):
        results = []
        page = 1
        while True:
            page_params = {**(params or {}), "page": page, "per_page": PAGE_SIZE}
            response = self._call("GET", path, params=page_params)
            if not isinstance(response, dict) or not isinstance(
                response.get("items"), list
            ):
                raise ValueError("Vikunja list response must contain an items array")
            items = response["items"]
            total_pages = response.get("total_pages")
            response_page = response.get("page")
            if type(total_pages) is not int or type(response_page) is not int:
                raise ValueError("Vikunja list response has invalid pagination")
            if (
                response_page != page
                or total_pages < 0
                or (items and total_pages < page)
            ):
                raise ValueError("Vikunja list response has inconsistent pagination")
            if not items:
                if total_pages not in {0, page}:
                    raise ValueError(
                        "Vikunja returned an empty page before the final page"
                    )
                return results
            results.extend(items)
            if page >= total_pages:
                return results
            page += 1

    def list_tasks(self, filter_query):
        return self._list(
            "/tasks",
            {
                "filter": filter_query,
                "format": "markdown",
                "sort_by": "updated",
                "order_by": "asc",
            },
        )

    def list_labels(self):
        return self._list("/labels")

    def get_task(self, task_id):
        task = self._call("GET", f"/tasks/{task_id}", params={"format": "markdown"})
        if not isinstance(task, dict):
            raise ValueError("Vikunja task response must be a JSON object")
        return task

    def list_comments(self, task_id):
        return self._list(
            f"/tasks/{task_id}/comments",
            {"format": "markdown", "order_by": "desc"},
        )

    def create_comment(self, task_id, comment):
        return self._call(
            "POST",
            f"/tasks/{task_id}/comments",
            params={"format": "markdown"},
            payload={"comment": comment},
        )
