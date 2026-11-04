"""Run deterministic parse evaluators in the worker and record Langfuse scores."""

import importlib.util
import json
import os
import urllib.request
from pathlib import Path

import yaml


SKIP_KEYS = {"project", "project_id"}


def load_parse_system_prompt(prompts_dir: Path) -> str:
    """Return the system text of the Dify 'Parse request' LLM node."""
    dsl = yaml.safe_load(
        (prompts_dir / "agents/dify/vikunja-clerk.dsl.yml").read_text(encoding="utf-8")
    )
    for node in dsl["workflow"]["graph"]["nodes"]:
        data = node.get("data", {})
        if data.get("type") == "llm" and data.get("title") == "Parse request":
            for message in data["prompt_template"]:
                if message.get("role") == "system":
                    return message["text"]
    raise ValueError("Parse request system prompt not found in DSL")


def load_schema_check(prompts_dir: Path):
    """Load check_reply from the source judge file for local evaluation."""
    path = prompts_dir / "agents/judges/parse-json-schema.py"
    spec = importlib.util.spec_from_file_location("parse_json_schema", path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load the parse schema evaluator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_reply


def call_role(system_prompt: str, user_text: str, role: str, base_url: str, api_key: str):
    """Call the configured LiteLLM role through its OpenAI-compatible endpoint."""
    body = json.dumps(
        {
            "model": role,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0,
            "max_tokens": 400,
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = json.loads(response.read())
    return payload["choices"][0]["message"]["content"], payload.get("model", "")


def _same(want, got) -> bool:
    if want is None:
        return got in (None, "")
    if isinstance(want, str) and isinstance(got, str):
        return want.strip().lower() == got.strip().lower()
    return want == got


def _evaluation(**values):
    from langfuse import Evaluation

    return Evaluation(**values)


def make_task(langfuse, system_prompt: str, role: str, base_url: str, api_key: str):
    def task(*, item, **kwargs):
        input_text = item.input["input"] if isinstance(item.input, dict) else item.input
        with langfuse.start_as_current_observation(
            name=f"vikunja-parse-{role}", as_type="generation", model=role, input=input_text
        ) as observation:
            reply, served = call_role(system_prompt, input_text, role, base_url, api_key)
            observation.update(output=reply, metadata={"served_model": served})
        return reply

    return task


def make_expected_fields_evaluator():
    def expected_fields_match(*, output, expected_output, **kwargs):
        expected = (expected_output or {}).get("structured_fields") or {}
        try:
            reply = json.loads(output)
        except (TypeError, json.JSONDecodeError):
            return _evaluation(name="expected-fields-match", value=0.0, comment="reply is not JSON")
        if not isinstance(reply, dict):
            return _evaluation(
                name="expected-fields-match", value=0.0, comment="reply is not a JSON object"
            )
        mismatches = []
        checked = 0
        for key, want in expected.items():
            if key in SKIP_KEYS:
                continue
            checked += 1
            got = reply.get(key)
            if not _same(want, got):
                mismatches.append(f"{key}: want {want!r} got {got!r}")
        return _evaluation(
            name="expected-fields-match",
            value=1.0 if not mismatches else 0.0,
            comment="; ".join(mismatches) or f"{checked} fields matched",
        )

    return expected_fields_match


def make_schema_evaluator(check_reply):
    def parse_json_schema_valid(*, output, **kwargs):
        problem = check_reply(output)
        return _evaluation(
            name="parse-json-schema-valid", value=1.0 if problem is None else 0.0, comment=problem or "valid"
        )

    return parse_json_schema_valid


def run_parse_experiment(
    experiment_name: str,
    dataset_name: str,
    role: str,
    prompts_dir: Path,
    base_url: str,
    api_key: str,
):
    from langfuse import Langfuse

    langfuse = Langfuse()
    system_prompt = load_parse_system_prompt(prompts_dir)
    check_reply = load_schema_check(prompts_dir)
    dataset = langfuse.get_dataset(dataset_name)
    return dataset.run_experiment(
        name=experiment_name,
        description=f"Parse eval for dataset {dataset_name} using local role {role}.",
        task=make_task(langfuse, system_prompt, role, base_url, api_key),
        evaluators=[make_expected_fields_evaluator(), make_schema_evaluator(check_reply)],
        metadata={"model_role": role, "source_commit": os.environ.get("SOURCE_COMMIT", "")},
    )
