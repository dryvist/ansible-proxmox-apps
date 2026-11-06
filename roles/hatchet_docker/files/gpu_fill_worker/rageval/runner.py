"""Retrieve generated questions, judge evidence locally, and publish aggregate results."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from adapter import LatencyGuardError, _check_latency_guard, run_chat
from fill.qa import completion_text


WINDOW = timedelta(hours=24)
MAX_CONTEXT_CHARS = 24000


class BackendError(RuntimeError):
    """A retrieval or summary request failed without retaining response details."""


def _endpoint(env, name, required=False):
    value = env.get(name, "").strip()
    if not value:
        if required:
            raise ValueError(f"{name} must be configured")
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    return value


def configured_backends(env):
    hindsight_url = _endpoint(env, "RAGEVAL_HINDSIGHT_RECALL_URL", required=True)
    hindsight_key = env.get("RAGEVAL_HINDSIGHT_API_KEY", "").strip()
    if not hindsight_key:
        raise ValueError("RAGEVAL_HINDSIGHT_API_KEY must be configured")
    backends = [
        {
            "name": "hindsight",
            "kind": "hindsight",
            "url": hindsight_url,
            "key": hindsight_key,
        }
    ]
    llama_url = _endpoint(env, "RAGEVAL_LLAMA_INDEX_QUERY_URL")
    if llama_url:
        backends.append(
            {
                "name": "llamaindex",
                "kind": "llamaindex",
                "url": llama_url,
                "key": env.get("RAGEVAL_LLAMA_INDEX_API_KEY", "").strip(),
            }
        )
    qdrant_url = _endpoint(env, "RAGEVAL_QDRANT_QUERY_URL")
    if qdrant_url:
        model = env.get("RAGEVAL_QDRANT_MODEL", "").strip()
        if not model:
            raise ValueError("RAGEVAL_QDRANT_MODEL must be configured with Qdrant")
        backends.append(
            {
                "name": "qdrant",
                "kind": "qdrant",
                "url": qdrant_url,
                "key": env.get("RAGEVAL_QDRANT_API_KEY", "").strip(),
                "model": model,
            }
        )
    return backends


def load_pairs(output_dir, roles, now):
    """Read valid generated pairs from the rolling 24-hour window."""
    pairs = []
    for role in roles:
        for path in sorted((Path(output_dir) / role).glob("*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    record = json.loads(line)
                    stamp = datetime.fromisoformat(record["timestamp"])
                    stamp = (
                        stamp.replace(tzinfo=timezone.utc)
                        if stamp.tzinfo is None
                        else stamp
                    )
                    question, answer = (
                        record["question"].strip(),
                        record["answer"].strip(),
                    )
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
                if (
                    question
                    and answer
                    and now - WINDOW <= stamp.astimezone(timezone.utc) <= now
                ):
                    pairs.append({"role": role, "question": question, "answer": answer})
    return pairs


def _http_request(url, body, headers, timeout_s):
    request = Request(
        url, data=body, headers=headers, method="POST" if body is not None else "GET"
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except HTTPError as response:
        return response.code, response.read()


def _request_json(backend, method, url, payload, timeout_s, request_fn):
    headers = {"Accept": "application/json"}
    key = backend.get("key")
    if key:
        headers["api-key" if backend["kind"] == "qdrant" else "Authorization"] = (
            key if backend["kind"] == "qdrant" else f"Bearer {key}"
        )
    body = json.dumps(payload).encode("utf-8") if method == "POST" else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        status, response_body = request_fn(url, body, headers, timeout_s)
    except Exception as exc:
        raise BackendError(type(exc).__name__) from None
    if not 200 <= status < 300:
        raise BackendError(f"HTTP {status}")
    try:
        return json.loads(response_body)
    except (ValueError, TypeError, UnicodeDecodeError):
        if backend["kind"] in {"llamaindex", "slack"}:
            return {"response": response_body.decode("utf-8", errors="replace")}
        raise BackendError("invalid JSON response") from None


def query_backend(backend, question, k, timeout_s, request_fn=None):
    request_fn = request_fn or _http_request
    if backend["kind"] == "hindsight":
        response = _request_json(
            backend,
            "POST",
            backend["url"],
            {"query": question, "budget": "low", "max_tokens": 4096},
            timeout_s,
            request_fn,
        )
    elif backend["kind"] == "qdrant":
        response = _request_json(
            backend,
            "POST",
            backend["url"],
            {
                "query": {"text": question, "model": backend["model"]},
                "limit": k,
                "with_payload": True,
            },
            timeout_s,
            request_fn,
        )
    else:
        url = (
            backend["url"]
            + ("&" if "?" in backend["url"] else "?")
            + urlencode({"text": question, "similarity_top_k": k})
        )
        response = _request_json(backend, "GET", url, None, timeout_s, request_fn)
    return extract_contexts(response, k)


def _text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "text",
            "page_content",
            "content",
            "document",
            "memory",
            "node",
            "payload",
        ):
            if key in value:
                found = _text(value[key])
                if found:
                    return found
    return ""


def extract_contexts(response, k):
    if not isinstance(response, dict):
        return []
    result = response.get("result")
    candidates = None
    if isinstance(result, dict):
        candidates = result.get("points")
    for key in ("results", "source_nodes", "sources", "nodes", "chunks", "points"):
        if candidates is None and isinstance(response.get(key), list):
            candidates = response[key]
    if not isinstance(candidates, list):
        return []
    contexts = []
    for item in candidates:
        text = _text(item)
        if text and text not in contexts:
            contexts.append(text[:MAX_CONTEXT_CHARS])
        if len(contexts) == k:
            break
    return contexts


def _judge_prompt(question, expected, contexts):
    sample = json.dumps(
        {
            "question": question,
            "expected_answer": expected,
            "retrieved_passages": contexts,
        },
        ensure_ascii=False,
    )
    return (
        "You are a strict RAG evaluation judge. Use only retrieved_passages as evidence. "
        "Write a concise answer to question from those passages. Set answer_recalled true only "
        "when the passages contain enough evidence to support expected_answer. Set "
        "answer_grounded true only when every factual claim in your answer is supported by "
        "the passages; use an empty answer and false when evidence is insufficient. "
        'Return only JSON with exactly these fields: {"answer":"...",'
        '"answer_recalled":true,"answer_grounded":true}.\nINPUT:\n' + sample
    )


def _judge(pair, contexts, platform, latency_guard, chat_fn):
    payload = {
        "payload": {
            "prompt": _judge_prompt(pair["question"], pair["answer"], contexts),
            "max_tokens": min(256, platform["max_tokens"]),
        }
    }
    content = completion_text(chat_fn(platform, payload, latency_guard=latency_guard))
    try:
        result = json.loads(content)
    except ValueError:
        raise ValueError("local judge returned invalid JSON") from None
    if (
        not isinstance(result, dict)
        or set(result) != {"answer", "answer_recalled", "answer_grounded"}
        or not isinstance(result["answer"], str)
        or type(result["answer_recalled"]) is not bool
        or type(result["answer_grounded"]) is not bool
    ):
        raise ValueError("local judge returned an invalid score")
    return result["answer_recalled"], bool(
        result["answer_grounded"] and result["answer"].strip()
    )


def _metric_bucket(total):
    return {
        "queries_total": total,
        "queries_scored": 0,
        "errors": 0,
        "recall_hits": 0,
        "grounded_answers": 0,
    }


def _summary(report):
    lines = [f"RAG eval {report['date']} — {report['status']}"]
    for name, metric in report["backends"].items():
        lines.append(
            f"{name}: recall@{report['k']}={metric['recall_at_k']}, "
            f"grounded={metric['answer_grounding']}, "
            f"scored={metric['queries_scored']}/{metric['queries_total']}, errors={metric['errors']}"
        )
    return "\n".join(lines)


def _write_report(results_dir, report):
    root = Path(results_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['date']}.json"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=root, delete=False
    ) as handle:
        temporary = handle.name
        json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temporary, target)
    return str(target)


def run_rageval(
    worker_config,
    *,
    latency_guard=None,
    chat_fn=None,
    request_fn=None,
    environ=None,
    now=None,
):
    """Evaluate every generated pair from the last day and emit aggregate-only results."""
    env = os.environ if environ is None else environ
    rageval = worker_config["rageval"]
    fill = worker_config["fill"]
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    now = now.astimezone(timezone.utc)
    backends = configured_backends(env)
    slack_url = _endpoint(env, "RAGEVAL_SLACK_WEBHOOK_URL", required=True)
    pairs = load_pairs(fill["output_dir"], fill["roles"], now)
    metrics = {backend["name"]: _metric_bucket(len(pairs)) for backend in backends}
    report = {
        "date": now.date().isoformat(),
        "status": "ok" if pairs else "empty",
        "k": rageval["k"],
        "backends": metrics,
    }
    chat_fn = chat_fn or run_chat
    request_fn = request_fn or _http_request
    timeout_s = max(
        platform["timeout_s"] for platform in worker_config["platforms"].values()
    )

    for backend in backends:
        metric = metrics[backend["name"]]
        for pair in pairs:
            try:
                contexts = query_backend(
                    backend,
                    pair["question"],
                    rageval["k"],
                    timeout_s,
                    request_fn=request_fn,
                )
                if contexts:
                    platform = worker_config["platforms"][fill["roles"][pair["role"]]]
                    recalled, grounded = _judge(
                        pair, contexts, platform, latency_guard, chat_fn
                    )
                else:
                    recalled, grounded = False, False
            except LatencyGuardError:
                report["status"] = "paused"
                break
            except BackendError:
                metric["errors"] += 1
                break
            except Exception:
                metric["errors"] += 1
                continue
            metric["queries_scored"] += 1
            metric["recall_hits"] += int(recalled)
            metric["grounded_answers"] += int(grounded)
        if report["status"] == "paused":
            break

    if report["status"] != "paused" and any(
        metric["errors"] for metric in metrics.values()
    ):
        report["status"] = "partial"
    for metric in metrics.values():
        scored = metric["queries_scored"]
        metric["recall_at_k"] = (
            round(metric["recall_hits"] / scored, 4) if scored else None
        )
        metric["answer_grounding"] = (
            round(metric["grounded_answers"] / scored, 4) if scored else None
        )
    report["results_file"] = _write_report(rageval["results_dir"], report)
    try:
        _request_json(
            {"kind": "slack", "key": None},
            "POST",
            slack_url,
            {"text": _summary(report)},
            timeout_s,
            request_fn,
        )
    except Exception:
        report["slack_summary_sent"] = False
        report["results_file"] = _write_report(rageval["results_dir"], report)
        raise BackendError("Slack summary delivery failed") from None
    report["slack_summary_sent"] = True
    report["results_file"] = _write_report(rageval["results_dir"], report)
    return report
