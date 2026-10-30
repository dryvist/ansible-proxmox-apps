"""Repeat state and suppression policy for the ntfy-Zammad bridge."""

import hashlib
import json
import os
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone

OPEN_STATES = ("new", "open")
ACTIVE_STATES = (*OPEN_STATES, "reopened")
CLOSED_STATES = ("closed",)
DEFAULT_REPEAT_INTERVAL_SECONDS = 3600
REOPEN_WINDOW_SECONDS = 24 * 60 * 60
SEARCH_LIMIT = 100


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
    # The alert identity is the title before the detail separator; producers
    # put changing counts and error text after it. Nothing inside the name is
    # rewritten, so alerts that differ by an id or number stay distinct.
    return "fk:ntfy:%s:%s" % (topic, (title or "").split(" — ", 1)[0])


def escape_lucene_phrase(value):
    # Backslash and double-quote are the only characters that break OUT of a
    # quoted Lucene phrase; every other special token (:, (, ), AND/OR/NOT)
    # is literal once inside one, so escaping just these two is sufficient.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_search_query(key, states=OPEN_STATES):
    return 'title:"%s" AND state.name:(%s)' % (
        escape_lucene_phrase(key),
        " OR ".join(states),
    )


def find_ticket(base, token, key, zammad_call):
    active = _search_tickets(base, token, key, ACTIVE_STATES, zammad_call)
    for result in active:
        ticket = _expanded_ticket(base, token, result, zammad_call)
        if ticket and _ticket_key(ticket) == key:
            ticket["state"] = ticket.get("state") or "open"
            return ticket

    closed = _search_tickets(base, token, key, CLOSED_STATES, zammad_call)
    matches = []
    for result in closed:
        ticket = _expanded_ticket(base, token, result, zammad_call)
        if ticket and _ticket_key(ticket) == key:
            ticket["state"] = ticket.get("state") or "closed"
            matches.append(ticket)
    if not matches:
        return None
    return max(matches, key=lambda ticket: ticket_closed_at(ticket) or float("-inf"))


def _search_tickets(base, token, key, states, zammad_call):
    query = build_search_query(key, states)
    url = "tickets/search?%s" % urllib.parse.urlencode(
        {"query": query, "limit": SEARCH_LIMIT, "expand": "true"}
    )
    found = zammad_call(base, token, url)
    if isinstance(found, list):
        tickets = found
    else:
        tickets = (found or {}).get("tickets") or []
    return [item if isinstance(item, dict) else {"id": item} for item in tickets]


def _expanded_ticket(base, token, ticket, zammad_call):
    if "title" in ticket and ("close_at" in ticket or ticket.get("state") in ACTIVE_STATES):
        return ticket
    ticket_id = ticket.get("id")
    if ticket_id is None:
        return ticket
    details = zammad_call(base, token, "tickets/%s" % ticket_id)
    if isinstance(details, dict) and details:
        return dict(ticket, **details)
    return ticket


def _ticket_key(ticket):
    title = ticket.get("title")
    if not isinstance(title, str):
        return None
    return title.split(" — ", 1)[0]


def ticket_state_name(ticket):
    state = ticket.get("state")
    if isinstance(state, dict):
        state = state.get("name")
    return str(state).lower() if state is not None else None


def ticket_closed_at(ticket):
    value = ticket.get("close_at")
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.timestamp()
    except (OverflowError, TypeError, ValueError):
        return None


def closed_within_reopen_window(ticket, now):
    closed_at = ticket_closed_at(ticket)
    if closed_at is None:
        return False
    age = now - closed_at
    return 0 <= age <= REOPEN_WINDOW_SECONDS


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
    if existing and ticket_state_name(existing) == "closed":
        if is_resolved(tags):
            return True
        if not closed_within_reopen_window(existing, now):
            return False
        if not bridge_opened_ticket(zammad_base, zammad_token, existing):
            return False
        zammad_call(
            zammad_base, zammad_token, "tickets/%s" % existing["id"],
            payload={
                "state": "reopened",
                "article": note(
                    message, tags, priority,
                    record.get("suppressed_count", 0), record.get("suppressed_since"),
                ),
            }, method="PUT",
        )
        remember_article(state_dir, records, key, current_state, now)
        return True

    if is_resolved(tags):
        if existing:
            # Avoid reading article history: it may be too large for the API.
            close_ticket = bridge_opened_ticket(zammad_base, zammad_token, existing)
            payload: dict = {"article": note(
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
