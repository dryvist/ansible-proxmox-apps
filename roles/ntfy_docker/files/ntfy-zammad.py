#!/usr/bin/env python3
"""ntfy CLI `command:` hook: open/append/close a Zammad ticket for one ntfy
message (see roles/ntfy_docker templates/client.yml.j2).

Contract: ntfy's own CLI runs this once per matching message (already
priority-filtered by client.yml's if: clause) with the message fields as
env vars (NTFY_TOPIC, NTFY_TITLE, NTFY_MESSAGE, NTFY_PRIORITY, NTFY_TAGS,
NTFY_ID -- see the ntfy CLI documentation), plus the connection settings from
the subscriber environment file (deployed alongside this script and inherited
because both run under the same systemd service).

Dedup uses the stable topic|title correlation key: the first firing creates a
ticket, then the bridge appends unchanged firing repeats at most once per
configured interval. Tag or priority changes append immediately; suppressed
repeat counts appear in the next article. A resolved or white_check_mark tag
always appends a recovery article, but closes only a ticket marked with the
bridge's ntfy-zammad-managed tag and absent from the close denylist. A
no-zammad tag skips ticket action entirely -- this is how the subscriber's OWN
failure alert (published back to the keystone topic below) avoids opening a
ticket about itself.

Adapted from splunk-homelab-alerts/bin/zammad.py's find-or-append pattern
(same estate, same Zammad instance) -- title-search dedup, stdlib-only
urllib, non-zero exit on failure.

ponytail: stdlib only, one file, no retry/backoff -- ntfy re-delivers nothing
on a command failure, so a failed message is spooled to the state dir and
replayed (oldest first, through the same correlation-key dedup) before the
next message is handled. After NTFY_ZAMMAD_FAILURE_THRESHOLD consecutive
failures it also pages `keystone` directly.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

OPEN_STATES = ("new", "open")
MANAGED_TAG = "ntfy-zammad-managed"
DEFAULT_REPEAT_INTERVAL_SECONDS = 3600
# ponytail: count cap only; the oldest spooled message is dropped (and logged)
# past it. Add an age cap if a long outage makes stale replays a problem.
SPOOL_MAX = 200


def env(key, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def parse_tags(raw):
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def is_resolved(tags):
    return "resolved" in tags or "white_check_mark" in tags


def alert_state(tags, priority=None):
    """Fingerprint tags and ntfy priority so state and severity changes append."""
    return {
        "resolved": is_resolved(tags),
        "tags": sorted(set(tags)),
        "priority": str(priority or ""),
    }


def should_skip(tags):
    return "no-zammad" in tags


def correlation_key(topic, title):
    # fk:<source>:<rule>:<entity> -- the same title-embedded dedup token
    # every other alerting source in this estate uses (see
    # splunk-homelab-alerts' zammad.py, adapted below). source is fixed to
    # "ntfy" (this subscriber owns every ntfy topic); rule is the topic;
    # entity is the alert's own title. Zammad's title search is exact-phrase,
    # not prefix, so this exact token is what a cross-source dedup lookup
    # must match.
    return "fk:ntfy:%s:%s" % (topic, title)


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


def close_denylist():
    values = json.loads(env("NTFY_ZAMMAD_CLOSE_DENYLIST", '["1000854"]'))
    if not isinstance(values, list):
        raise ValueError("NTFY_ZAMMAD_CLOSE_DENYLIST must be a JSON array")
    return {str(value) for value in values}


def bridge_opened_ticket(base, token, ticket):
    """Require a known non-denied number and the bridge's persistent tag."""
    ticket_id = ticket["id"]
    number = ticket.get("number")
    if number is None:
        details = zammad_call(base, token, "tickets/%s" % ticket_id)
        number = details.get("number") if isinstance(details, dict) else None
    if number is None or str(number) in close_denylist():
        return False
    tags = zammad_call(
        base,
        token,
        "tags?%s" % urllib.parse.urlencode({"object": "Ticket", "o_id": ticket_id}),
    )
    return isinstance(tags, dict) and MANAGED_TAG in (tags.get("tags") or [])


def zammad_call(base, token, path, payload=None, method=None):
    url = "%s/%s" % (base.rstrip("/"), path.lstrip("/"))
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json", "Authorization": "Token token=%s" % token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
        return json.loads(body) if body else {}


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


def find_ticket(base, token, key):
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


def publish_self_alert(ntfy_base, topic, message):
    req = urllib.request.Request(
        "%s/%s" % (ntfy_base.rstrip("/"), topic),
        data=message.encode(),
        method="POST",
        headers={"Tags": "no-zammad", "Priority": "high", "Title": "ntfy-zammad failing"},
    )
    urllib.request.urlopen(req, timeout=10)


def counter_path(state_dir):
    return os.path.join(state_dir, "failures")


def record_failure(state_dir, threshold, ntfy_base, keystone_topic):
    os.makedirs(state_dir, exist_ok=True)
    path = counter_path(state_dir)
    try:
        with open(path) as f:
            n = int(f.read().strip() or "0")
    except (FileNotFoundError, ValueError):
        n = 0
    n += 1
    with open(path, "w") as f:
        f.write(str(n))
    if n == threshold and ntfy_base and keystone_topic:
        try:
            publish_self_alert(ntfy_base, keystone_topic, "ntfy-zammad has failed %d consecutive times" % n)
        except Exception:
            pass  # the self-alert path failing is not recoverable here


def clear_failures(state_dir):
    path = counter_path(state_dir)
    if os.path.exists(path):
        os.remove(path)


# The spool holds the alert payload only (topic, title, message, tags) -- never
# a credential -- one 0600 JSON file per message, named so a sort is oldest
# first.
def spool_dir(state_dir):
    return os.path.join(state_dir, "spool")


def spool_message(state_dir, msg, max_files=SPOOL_MAX):
    d = spool_dir(state_dir)
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, "%020d-%d.json" % (time.time_ns(), os.getpid()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(msg, f)
    names = sorted(os.listdir(d))
    for name in names[: max(0, len(names) - max_files)]:
        os.remove(os.path.join(d, name))
        sys.stderr.write("WARN spool full (%d); dropped oldest message %s\n" % (max_files, name))


def replay_spool(state_dir, handler):
    """Handle each spooled message oldest first; stop (and keep the rest) at
    the first failure, which the caller then spools behind."""
    d = spool_dir(state_dir)
    if not os.path.isdir(d):
        return
    for name in sorted(os.listdir(d)):
        path = os.path.join(d, name)
        with open(path) as f:
            msg = json.load(f)
        try:
            handler(msg)
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                raise
            # A 4xx will fail the same way on every replay; drop it rather
            # than let one bad payload block the messages behind it.
            sys.stderr.write("WARN dropped spooled message %s: Zammad HTTP %s\n" % (name, exc.code))
        os.remove(path)


def is_transient(exc):
    """Zammad unreachable or failing server-side: worth spooling for replay."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


# ponytail: find_ticket-then-create below is check-then-act -- two ntfy
# messages on the same topic|title processed concurrently could both miss
# the existing ticket and each open a duplicate. ntfy runs this hook
# synchronously per subscriber process, so it needs a real lock only if a
# topic is ever fanned out to multiple concurrent workers.
def current_message():
    topic = env("NTFY_TOPIC")
    return {
        "topic": topic,
        "title": env("NTFY_TITLE") or topic or "ntfy alert",
        "message": env("NTFY_MESSAGE", ""),
        "tags": parse_tags(env("NTFY_TAGS", "")),
        "priority": env("NTFY_PRIORITY", ""),
    }


def handle(msg):
    topic, title, message, tags = msg["topic"], msg["title"], msg["message"], msg["tags"]
    priority = msg.get("priority")

    if should_skip(tags):
        return

    zammad_base = env("ZAMMAD_API_URL")
    zammad_token = env("ZAMMAD_API_TOKEN")
    if not zammad_base or not zammad_token:
        raise RuntimeError("ZAMMAD_API_URL/ZAMMAD_API_TOKEN not set")

    state_dir = env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad")
    repeat_interval = int(
        env("NTFY_ZAMMAD_REPEAT_INTERVAL_SECONDS", str(DEFAULT_REPEAT_INTERVAL_SECONDS))
    )
    if repeat_interval < 0:
        raise ValueError("NTFY_ZAMMAD_REPEAT_INTERVAL_SECONDS must be non-negative")

    key = correlation_key(topic, title)
    existing = find_ticket(zammad_base, zammad_token, key)
    records = load_repeat_state(state_dir)
    record_key = repeat_state_key(key)
    record = records.get(record_key, {})
    now = time.time()
    current_state = alert_state(tags, priority)

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
            save_repeat_state(state_dir, records, key, {
                "state": current_state,
                "last_article_at": now,
                "suppressed_count": 0,
                "suppressed_since": None,
            })
        return

    if existing:
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
            return

        zammad_call(
            zammad_base, zammad_token, "tickets/%s" % existing["id"],
            payload={"article": note(
                message, tags, priority,
                record.get("suppressed_count", 0), record.get("suppressed_since"),
            )}, method="PUT",
        )
        save_repeat_state(state_dir, records, key, {
            "state": current_state,
            "last_article_at": now,
            "suppressed_count": 0,
            "suppressed_since": None,
        })
        return

    groups = json.loads(env("NTFY_ZAMMAD_TOPIC_GROUPS_JSON", "{}"))
    group = groups.get(topic, "Incidents")
    # "fk:... — <human summary>", same layout as every other source: the
    # fk: token stays the exact-phrase dedup key, the summary after the dash
    # is only for a human reading the ticket list.
    summary = message.splitlines()[0] if message else title
    me = zammad_call(zammad_base, zammad_token, "users/me")
    created = zammad_call(
        zammad_base, zammad_token, "tickets",
        payload=new_ticket(key, summary, group, note(message, tags, priority), me["id"]),
        method="POST",
    )
    if isinstance(created, dict) and created.get("id") is not None:
        zammad_call(
            zammad_base, zammad_token, "tags/add",
            payload={"item": MANAGED_TAG, "object": "Ticket", "o_id": created["id"]},
            method="POST",
        )
    save_repeat_state(state_dir, records, key, {
        "state": current_state,
        "last_article_at": now,
        "suppressed_count": 0,
        "suppressed_since": None,
    })


def new_ticket(key, summary, group, article, customer_id):
    # Zammad requires customer_id when an agent token creates a ticket; the
    # token's own user (svc-ntfy) is the customer, so attribution stays
    # "own actor, own token".
    return {
        "title": "%s — %s" % (key, summary),
        "group": group, "state": "new", "article": article,
        "customer_id": customer_id,
    }


def selftest():
    import tempfile

    assert correlation_key("network", "WAN down") == "fk:ntfy:network:WAN down"
    assert should_skip(["no-zammad"]) is True
    assert should_skip(["high"]) is False
    assert is_resolved(["resolved"]) is True
    assert is_resolved(["white_check_mark", "info"]) is True
    assert is_resolved(["high"]) is False
    assert parse_tags(" a, b ,,c") == ["a", "b", "c"]
    assert first_ticket([]) is None
    assert first_ticket({}) is None
    assert first_ticket({"tickets": []}) is None
    assert (first_ticket([{"id": 7, "title": "t"}]) or {})["id"] == 7
    assert first_ticket({"tickets": [9], "assets": {}}) == {"id": 9}
    t = new_ticket("fk:ntfy:x:y", "s", "Incidents", {"body": "b"}, 42)
    assert t["customer_id"] == 42 and t["title"] == "fk:ntfy:x:y — s"
    n = note("body text", ["a", "b"])
    assert n["internal"] is True and "body text" in n["body"] and "a, b" in n["body"]

    # Lucene phrase escaping: :, (, ), AND/OR/NOT are literal once inside a
    # correctly-escaped quoted phrase; only backslash and " can break out,
    # so escaping just those two keeps the hostile value INSIDE one phrase.
    assert escape_lucene_phrase('a\\b"c') == 'a\\\\b\\"c'
    hostile = 'net" OR state.name:closed AND title:"x (foo:bar) NOT y'
    hostile_key = correlation_key("topic", hostile)
    query = build_search_query(hostile_key)
    assert query == 'title:"%s" AND state.name:(new OR open)' % escape_lucene_phrase(
        hostile_key
    )

    # Self-alert must fire exactly once when crossing the threshold, not on
    # every failure afterward, and a success must reset the counter so the
    # NEXT outage can alert again.
    with tempfile.TemporaryDirectory() as state_dir:
        fired = []
        orig_publish = globals()["publish_self_alert"]
        globals()["publish_self_alert"] = lambda *a, **k: fired.append(1)
        try:
            for _ in range(5):
                record_failure(state_dir, 3, "http://ntfy", "keystone")
            assert fired == [1], "self-alert must fire exactly once crossing threshold"
            clear_failures(state_dir)
            for _ in range(3):
                record_failure(state_dir, 3, "http://ntfy", "keystone")
            assert fired == [1, 1], "counter reset must allow a second alert on the next outage"
        finally:
            globals()["publish_self_alert"] = orig_publish

    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    _state_dir = env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad")
    _msg = current_message()
    try:
        replay_spool(_state_dir, handle)
        handle(_msg)
    except urllib.error.HTTPError as exc:
        sys.stderr.write(
            "ERROR Zammad HTTP %s %s: %s\n" % (exc.code, exc.url, exc.read().decode()[:500])
        )
        if is_transient(exc) and not should_skip(_msg["tags"]):
            spool_message(_state_dir, _msg)
        record_failure(
            env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad"),
            int(env("NTFY_ZAMMAD_FAILURE_THRESHOLD", "3")),
            env("NTFY_BASE_URL", ""),
            env("NTFY_ZAMMAD_KEYSTONE_TOPIC", ""),
        )
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - ntfy needs a non-zero exit, not a traceback
        # Full traceback to stderr: the bare message alone ("Expecting property
        # name ...") does not say which step or input failed.
        sys.stderr.write(
            "ERROR %s: %s (topic=%s title=%s)\n%s"
            % (type(exc).__name__, exc, env("NTFY_TOPIC"), env("NTFY_TITLE"), traceback.format_exc())
        )
        if is_transient(exc) and not should_skip(_msg["tags"]):
            spool_message(_state_dir, _msg)
        record_failure(
            env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad"),
            int(env("NTFY_ZAMMAD_FAILURE_THRESHOLD", "3")),
            env("NTFY_BASE_URL", ""),
            env("NTFY_ZAMMAD_KEYSTONE_TOPIC", ""),
        )
        sys.exit(1)
    else:
        clear_failures(env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad"))
