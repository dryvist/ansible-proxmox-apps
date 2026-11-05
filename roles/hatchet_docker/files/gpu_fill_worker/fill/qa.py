"""Grounded question/answer workload: prompt, strict JSON validation, and JSONL output."""

import json
import logging
import threading
from datetime import timezone
from pathlib import Path

PAIRS_PER_CHUNK = 5
logger = logging.getLogger("gpu_fill.qa")


class MalformedOutput(ValueError):
    """The model reply is not the strict JSON shape this workload requires."""


def build_prompt(chunk_text):
    return (
        f"Write exactly {PAIRS_PER_CHUNK} question and answer pairs about the TEXT below. "
        "Vary the question types and difficulty. Every question must be answerable from the TEXT "
        "alone, and every answer must be stated in the TEXT. Do not use outside knowledge.\n"
        'Reply with only a JSON object of this exact shape and no other text: '
        '{"pairs": [{"question": "<question>", "answer": "<answer>"}]}\n'
        "TEXT:\n<<<\n" + chunk_text + "\n>>>"
    )


def completion_text(result):
    """Return the assistant message text from an OpenAI-style chat completion object."""
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MalformedOutput("chat completion has no message content") from exc
    if not isinstance(content, str):
        raise MalformedOutput("chat completion content is not a string")
    return content


def parse_pairs(content):
    """Return (valid_pairs, invalid_count) from a strict JSON reply.

    Raises MalformedOutput when the reply is not JSON, has no pairs list, or has no valid pair.
    A pair is valid only when it has exactly question and answer, both non-empty strings.
    """
    try:
        payload = json.loads(content)
    except ValueError as exc:
        raise MalformedOutput("reply is not valid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("pairs"), list):
        raise MalformedOutput("reply JSON has no pairs list")
    valid, invalid = [], 0
    for item in payload["pairs"]:
        if (
            isinstance(item, dict)
            and set(item) == {"question", "answer"}
            and isinstance(item["question"], str)
            and isinstance(item["answer"], str)
            and item["question"].strip()
            and item["answer"].strip()
        ):
            valid.append(item)
        else:
            invalid += 1
    if not valid:
        raise MalformedOutput("reply has no valid question and answer pair")
    return valid, invalid


def make_records(pairs, chunk_id, role, model, when):
    stamp = when.isoformat()
    return [
        {
            "chunk_id": chunk_id,
            "role": role,
            "model": model,
            "question": pair["question"],
            "answer": pair["answer"],
            "timestamp": stamp,
        }
        for pair in pairs
    ]


class JsonlWriter:
    """Appends records to <output_dir>/<role>/<UTC date>.jsonl. Thread-safe."""

    def __init__(self, output_dir):
        self._root = Path(output_dir)
        self._lock = threading.Lock()

    def append(self, role, records, when):
        if not records:
            return 0
        day = when.astimezone(timezone.utc).strftime("%Y-%m-%d")
        path = self._root / role / f"{day}.jsonl"
        text = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        )
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)
        return len(records)


def run_fill(chunk, *, role, platform_cfg, chat, latency_guard, writer, when):
    """Generate pairs for one chunk and append the valid ones.

    chat is adapter.run_chat. A LatencyGuardError from it propagates to the caller.
    Malformed replies are counted and logged, and nothing is written for them.
    """
    payload = {
        "payload": {
            "prompt": build_prompt(chunk.text),
            "max_tokens": platform_cfg["max_tokens"],
        }
    }
    result = chat(platform_cfg, payload, latency_guard=latency_guard)
    try:
        valid, invalid = parse_pairs(completion_text(result))
    except MalformedOutput as exc:
        logger.warning("malformed fill output role=%s chunk=%s: %s", role, chunk.chunk_id, exc)
        return {"status": "malformed", "chunk_id": chunk.chunk_id, "written": 0, "invalid": 0}
    # A reply that is not exactly PAIRS_PER_CHUNK valid pairs is partial: its valid pairs are kept, and the status says so.
    status = "written" if not invalid and len(valid) == PAIRS_PER_CHUNK else "partial"
    if status == "partial":
        logger.warning(
            "partial fill output role=%s chunk=%s valid=%d invalid=%d",
            role,
            chunk.chunk_id,
            len(valid),
            invalid,
        )
    records = make_records(valid, chunk.chunk_id, role, platform_cfg["model"], when)
    written = writer.append(role, records, when)
    return {"status": status, "chunk_id": chunk.chunk_id, "written": written, "invalid": invalid}
