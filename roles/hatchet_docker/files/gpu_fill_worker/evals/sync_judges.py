"""Sync only LLM-as-judge evaluator definitions from the prompts checkout."""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml


def _request(method: str, path: str, body: dict | None = None) -> dict:
    host = os.environ["LANGFUSE_HOST"].rstrip("/")
    token = base64.b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{host}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{method} {path} -> HTTP {error.code}: {detail}") from None


def llm_judge_body(defn: dict) -> dict:
    criteria = "\n".join(f"- {criterion}" for criterion in defn["criteria"])
    prompt = f"{defn['prompt_header']}\nCriteria:\n{criteria}\n"
    return {
        "name": defn["name"],
        "description": defn["description"],
        "type": "llm_as_judge",
        "prompt": prompt,
        "modelConfig": {"provider": defn["connection"], "model": defn["model"]},
        "variableMapping": [
            {"variable": variable, "source": source}
            for variable, source in defn["variable_mapping"].items()
        ],
        "outputDefinition": {
            "dataType": defn["output"]["data_type"],
            "scoreReasoningInstructions": defn["output"]["reasoning_instructions"],
        },
    }


def list_evaluators(request_fn) -> dict[str, dict]:
    evaluators: dict[str, dict] = {}
    cursor = None
    seen: set[str] = set()
    while True:
        params = {"limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        page = request_fn("GET", f"/api/public/v2/evaluators?{urllib.parse.urlencode(params)}")
        for evaluator in page.get("data", []):
            evaluators[evaluator["name"]] = evaluator
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor:
            return evaluators
        if cursor in seen:
            raise RuntimeError(f"evaluator pagination repeated cursor {cursor!r}")
        seen.add(cursor)


def sync(judges_dir: Path, request_fn=None) -> list[str]:
    request_fn = request_fn or _request
    existing = list_evaluators(request_fn)
    report = []
    for path in sorted(judges_dir.glob("*.yaml")):
        definition = yaml.safe_load(path.read_text(encoding="utf-8"))
        if definition["type"] == "code":
            report.append(f"skipped {definition['name']}: hosted code evaluators off")
            continue
        if definition["name"] in existing:
            report.append(f"exists {definition['name']} type={existing[definition['name']].get('type')}")
            continue
        if definition["type"] != "llm_as_judge":
            raise ValueError(f"unknown evaluator type in {path.name}: {definition['type']}")
        try:
            created = request_fn("POST", "/api/public/v2/evaluators", llm_judge_body(definition))
        except RuntimeError as error:
            report.append(f"blocked {definition['name']}: {error}")
            continue
        report.append(f"created {definition['name']} id={created.get('id')}")
    return report
