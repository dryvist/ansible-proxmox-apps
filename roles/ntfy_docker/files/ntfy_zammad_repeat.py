"""Repeat state and suppression policy for the ntfy-Zammad bridge."""

import hashlib
import json
import os
import tempfile
import time
import urllib.parse

OPEN_STATES = ("new", "open")
DEFAULT_REPEAT_INTERVAL_SECONDS = 3600


def is_resolved(tags):
    return "resolved" in tags or "white_check_mark" in tags


def alert_state(tags, priority=None):
    """Fingerprint tags and ntfy priority so state and severity changes append."""
    return {
        "resolved": is_resolved(tags),
        "tags": sorted(set(tags)),
        "priority": str(priority or ""),
    }


def correlation_key(topic, title):
    # fk:<source>:<rule>:<entity> -- the same title-embedded dedup token
    # every other alerting source in this estate uses (see
    # splunk-homelab-alerts' zammad.py, adapted below). source is fixed to
    # "ntfy" (this subscriber owns every ntfy topic); rule is the topic;
    # entity is the alert's own title. Zammad's title search is exact-phrase,
    # not prefix, so this exact token is what a cross-source dedup lookup
    # must match.
    return "fk:ntfy:%s:%s" % (topic, title)


def escape_lucene_phrase(value):
    # Backslash and double-quote are the only characters that break OUT of a
    # quoted Lucene phrase; every other special token (:, (, ), AND/OR/NOT)
    # is literal once inside one, so escaping just these two is sufficient.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_search_query(key):
    return 'title:"%s" AND state.name:(%s)' % (
        escape_lucene_phrase(key),
        " OR ".join(OPEN_STATES),
    )


def find_ticket(base, token, key, zammad_call):
    query = build_search_query(key)
    url = "tickets/search?%s" % urllib.parse.urlencode(
        {"query": query, "limit": 1, "expand": "true"}
    )
    return first_ticket(zammad_call(base, token, url))


def first_ticket(found):
    # Zammad's search answers with a list of tickets (expand=true, and an
    # empty result) or with {"tickets": [<id>, ...], "assets": ...}. Either
    # way the caller needs only the first ticket's id.
    tickets = found if isinstance(found, list) else (found.get("tickets") or [])
    if not tickets:
        return None
    first = tickets[0]
    return first if isinstance(first, dict) else {"id": first}


def format_utc(timestamp):
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp))


def note(message, tags, priority=None, suppressed_count=0, suppressed_since=None):
    lines = [message or ""]
    if tags:
        lines.append("")
        lines.append("Tags: %s" % ", ".join(tags))
    if priority not in (None, ""):
        lines.append("Priority: %s" % priority)
    if suppressed_count:
        lines.extend([
            "",
            "%d repeats suppressed since %s" % (
                suppressed_count, format_utc(suppressed_since)
            ),
        ])
    return {"body": "\n".join(lines), "type": "note", "internal": True}


def repeat_state_path(state_dir):
    return os.path.join(state_dir, "repeat-state.json")


def repeat_state_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def load_repeat_state(state_dir):
    try:
        with open(repeat_state_path(state_dir)) as f:
            state = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(state, dict):
        raise ValueError("repeat state file must contain a JSON object")
    return state


def load_repeat_record(state_dir, key):
    records = load_repeat_state(state_dir)
    return records, records.get(repeat_state_key(key), {})


def save_repeat_state(state_dir, state, key, record):
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    state[repeat_state_key(key)] = record
    fd, temp_path = tempfile.mkstemp(prefix=".repeat-state-", dir=state_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, repeat_state_path(state_dir))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def remember_article(state_dir, records, key, current_state, now):
    save_repeat_state(state_dir, records, key, {
        "state": current_state,
        "last_article_at": now,
        "suppressed_count": 0,
        "suppressed_since": None,
    })


def suppress_repeat(state_dir, records, key, record, current_state, now, repeat_interval):
    same_state = record.get("state") == current_state
    last_article_at = record.get("last_article_at")
    if (
        same_state
        and last_article_at is not None
        and now - float(last_article_at) < repeat_interval
    ):
        record["suppressed_count"] = int(record.get("suppressed_count", 0)) + 1
        if record.get("suppressed_since") is None:
            record["suppressed_since"] = now
        save_repeat_state(state_dir, records, key, record)
        return True
    return False


def handle_existing(
    zammad_base, zammad_token, state_dir, records, key, record, current_state,
    now, repeat_interval, existing, message, tags, priority,
    bridge_opened_ticket, zammad_call,
):
    if is_resolved(tags):
        if existing:
            # Avoid reading article history: it may be too large for the API.
            close_ticket = bridge_opened_ticket(zammad_base, zammad_token, existing)
            payload = {"article": note(
                message, tags, priority,
                record.get("suppressed_count", 0), record.get("suppressed_since"),
            )}
            if close_ticket:
                payload["state"] = "closed"
            zammad_call(
                zammad_base, zammad_token, "tickets/%s" % existing["id"],
                payload=payload, method="PUT",
            )
            remember_article(state_dir, records, key, current_state, now)
        return True

    if existing:
        if suppress_repeat(
            state_dir, records, key, record, current_state, now, repeat_interval
        ):
            return True

        zammad_call(
            zammad_base, zammad_token, "tickets/%s" % existing["id"],
            payload={"article": note(
                message, tags, priority,
                record.get("suppressed_count", 0), record.get("suppressed_since"),
            )}, method="PUT",
        )
        remember_article(state_dir, records, key, current_state, now)
        return True

    return False
