"""Nightly Langfuse trace sampling, judging, scoring, and lessons delivery."""

import os
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from adapter import LatencyGuardError
from tracejudge.client import LangfuseClient, post_slack, write_lessons
from tracejudge.judge import SCORES, judge_trace, safe_text, summarize_failures


def _group_keys(row):
    groups = set()
    name = row.get("traceName")
    if not isinstance(name, str) or not name.strip():
        if row.get("isRootObservation"):
            name = row.get("name")
        else:
            name = None
    if isinstance(name, str) and name.strip():
        groups.add(("name", name.strip()))
    tags = row.get("tags")
    if isinstance(tags, list):
        groups.update(("tag", tag.strip()) for tag in tags if isinstance(tag, str) and tag.strip())
    return groups


def sample_traces(rows, sample_per_agent):
    """Rebuild traces from observation rows and cap the newest samples per name or tag."""
    traces = {}
    for row in rows:
        trace_id = row.get("traceId")
        if not isinstance(trace_id, str) or not trace_id:
            continue
        trace = traces.setdefault(
            trace_id,
            {"trace_id": trace_id, "name": row.get("traceName") or "", "tags": set(),
             "groups": set(), "observations": [], "seen": set(), "latest": ""},
        )
        trace["groups"].update(_group_keys(row))
        tags = row.get("tags")
        if isinstance(tags, list):
            trace["tags"].update(tag for tag in tags if isinstance(tag, str))
        if not trace["name"] and row.get("traceName"):
            trace["name"] = row["traceName"]
        observation_id = row.get("id")
        if observation_id and observation_id in trace["seen"]:
            continue
        if observation_id:
            trace["seen"].add(observation_id)
        trace["observations"].append(row)
        trace["latest"] = max(trace["latest"], str(row.get("startTime") or ""))

    counts = defaultdict(int)
    selected = []
    for trace in sorted(traces.values(), key=lambda item: item["latest"], reverse=True):
        available = sorted(group for group in trace["groups"] if counts[group] < sample_per_agent)
        if not available:
            continue
        trace["groups"] = available
        trace["tags"] = sorted(trace["tags"])
        trace["observations"].sort(key=lambda row: str(row.get("startTime") or ""))
        del trace["seen"]
        for group in available:
            counts[group] += 1
        selected.append(trace)
    return selected


def _utc_bounds(run_time):
    if run_time.tzinfo is None:
        raise ValueError("tracejudge run_time must be timezone-aware")
    previous_day = run_time.astimezone(timezone.utc).date() - timedelta(days=1)
    start = datetime.combine(previous_day, time.min, timezone.utc)
    end = start + timedelta(days=1)
    return previous_day, start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def run_daily(tracejudge_config, platform, latency_guard=None, now=None, request_fn=None, chat_fn=None):
    public_env = tracejudge_config["auth_env"]["public_key"]
    secret_env = tracejudge_config["auth_env"]["secret_key"]
    public_key = os.environ.get(public_env)
    secret_key = os.environ.get(secret_env)
    webhook_env = tracejudge_config["slack_webhook_env"]
    webhook = os.environ.get(webhook_env)
    if not public_key or not secret_key or not webhook:
        raise ValueError("tracejudge credentials and Slack webhook must be set in the environment")

    run_time = now or datetime.now(timezone.utc)
    score_date, start, end = _utc_bounds(run_time)
    client = LangfuseClient(
        tracejudge_config["langfuse_base_url"], public_key, secret_key,
        platform["timeout_s"], request_fn,
    )
    traces = sample_traces(
        client.observations(start, end), tracejudge_config["sample_per_agent"]
    )
    scored = {}
    for trace in traces:
        result = judge_trace(trace, platform, latency_guard, chat_fn)
        scored[trace["trace_id"]] = result
        for name in SCORES:
            client.create_score(
                trace["trace_id"], name, result[name]["score"], result[name]["reason"], score_date
            )

    by_agent = defaultdict(list)
    for trace in traces:
        for group in trace["groups"]:
            by_agent[group].append(scored[trace["trace_id"]])
    summaries = []
    for (agent_kind, agent), agent_scores in sorted(by_agent.items()):
        safe_agent = safe_text(agent, 120)
        patterns = summarize_failures(safe_agent, agent_scores, platform, latency_guard, chat_fn)
        averages = {
            name: round(sum(scores[name]["score"] for scores in agent_scores) / len(agent_scores), 2)
            for name in SCORES
        }
        pattern_text = "; ".join(
            f"{pattern['pattern']} ({pattern['count']} sampled traces)" for pattern in patterns
        ) or f"No recurring failure patterns were found in {len(agent_scores)} sampled traces."
        summaries.append({
            "date": score_date.isoformat(),
            "agent": safe_agent,
            "agent_kind": agent_kind,
            "trace_count": len(agent_scores),
            "average_scores": averages,
            "top_failure_patterns": patterns,
            "context": "daily GPU agent performance lessons",
            "document_id": "tracejudge-" + score_date.isoformat() + "-" + str(
                uuid5(NAMESPACE_URL, f"{score_date}:{agent_kind}:{safe_agent}")
            ),
            "content": (
                f"Agent: {safe_agent} ({agent_kind})\n"
                f"Date: {score_date.isoformat()}\n"
                f"Sampled traces: {len(agent_scores)}\n"
                f"Top failure patterns: {pattern_text}"
            ),
        })

    write_lessons(tracejudge_config["output_dir"], score_date, summaries)
    if summaries:
        post_slack(webhook, score_date, summaries, request_fn)
    return {"date": score_date.isoformat(), "traces_scored": len(scored), "agents_summarized": len(summaries)}


def build_tasks(hatchet, tracejudge_config, platforms, latency_guard=None):
    from hatchet_sdk import Priority

    platform = platforms[tracejudge_config["platform"]]

    def judge_previous_day(_input, _ctx):
        try:
            return run_daily(tracejudge_config, platform, latency_guard)
        except LatencyGuardError:
            raise
        except Exception as exc:
            raise RuntimeError(f"trace judging failed: {type(exc).__name__}") from None

    return [
        hatchet.task(
            name="tracejudge-previous-day",
            on_crons=[tracejudge_config["cron"]],
            retries=6,
            backoff_factor=2.0,
            backoff_max_seconds=300,
            execution_timeout=timedelta(hours=6),
            default_priority=Priority.LOW,
        )(judge_previous_day)
    ]
