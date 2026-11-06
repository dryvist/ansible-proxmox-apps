"""Langfuse, Slack, and daily JSONL I/O for scheduled trace judging."""

import base64
import json
import os
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5


def _http_request(method, url, body, headers, timeout_s):
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except HTTPError as response:
        return response.code, response.read()


class LangfuseClient:
    def __init__(self, base_url, public_key, secret_key, timeout_s, request_fn=None):
        credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
        }
        self.timeout_s = timeout_s
        self.request = request_fn or _http_request

    def observations(self, start_time, end_time):
        """Yield bounded v2 observation pages, following every returned cursor."""
        cursor = None
        seen_cursors = set()
        while True:
            query = {
                "fields": "core,basic,time,io,trace_context,tools",
                "fromStartTime": start_time,
                "toStartTime": end_time,
                "limit": 1000,
            }
            if cursor:
                query["cursor"] = cursor
            status, body = self.request(
                "GET",
                f"{self.base_url}/api/public/v2/observations?{urlencode(query)}",
                None,
                self.headers,
                self.timeout_s,
            )
            payload = _json_response(status, body, "Langfuse observations API")
            rows = payload.get("data")
            meta = payload.get("meta")
            if not isinstance(rows, list) or not isinstance(meta, dict):
                raise ValueError("Langfuse observations response has invalid data or meta")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Langfuse observation must be an object")
                yield row
            cursor = meta.get("cursor")
            if not cursor:
                return
            if not isinstance(cursor, str) or cursor in seen_cursors:
                raise ValueError("Langfuse observations cursor is invalid or repeated")
            seen_cursors.add(cursor)

    def create_score(self, trace_id, name, value, comment, score_date):
        score_id = str(uuid5(NAMESPACE_URL, f"tracejudge:{trace_id}:{name}:{score_date}"))
        payload = {
            "id": score_id,
            "traceId": trace_id,
            "name": name,
            "value": value,
            "dataType": "NUMERIC",
            "comment": comment,
            "timestamp": f"{score_date.isoformat()}T23:59:59.000Z",
        }
        status, body = self.request(
            "POST",
            f"{self.base_url}/api/public/scores",
            json.dumps(payload).encode("utf-8"),
            {**self.headers, "Content-Type": "application/json"},
            self.timeout_s,
        )
        _json_response(status, body, "Langfuse score API")


def _json_response(status, body, label):
    if not 200 <= status < 300:
        raise RuntimeError(f"{label} returned HTTP {status}")
    try:
        value = json.loads(body) if body else {}
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} response must be a JSON object")
    return value


def write_lessons(output_dir, score_date, summaries):
    output_dir = os.fspath(output_dir)
    os.makedirs(output_dir, mode=0o755, exist_ok=True)
    destination = os.path.join(output_dir, f"lessons-{score_date.isoformat()}.jsonl")
    file_descriptor, temporary = tempfile.mkstemp(prefix=".tracejudge-", dir=output_dir)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            for summary in summaries:
                stream.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def post_slack(webhook_url, score_date, summaries, request_fn=None):
    """Post the generated lessons in bounded webhook messages without trace payloads."""
    lines = [f"Daily agent lessons · {score_date.isoformat()}"]
    for summary in summaries:
        label = f"{summary['agent_kind']}: {summary['agent']}"
        patterns = summary["top_failure_patterns"]
        if patterns:
            lines.append(f"• {label} — " + "; ".join(
                f"{item['pattern']} ({item['count']})" for item in patterns[:3]
            ))
        else:
            lines.append(f"• {label} — no recurring failure patterns")

    messages = []
    current = lines[0]
    for line in lines[1:]:
        if len(current) + len(line) + 1 > 3500:
            messages.append(current)
            current = lines[0] + " (continued)\n" + line
        else:
            current += "\n" + line
    if len(lines) > 1 or not summaries:
        messages.append(current)

    request = request_fn or _http_request
    for message in messages:
        status, _ = request(
            "POST",
            webhook_url,
            json.dumps({"text": message}).encode("utf-8"),
            {"Content-Type": "application/json"},
            30,
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"Slack webhook returned HTTP {status}")
