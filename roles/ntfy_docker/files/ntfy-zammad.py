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

ponytail: stdlib only, the prior one-file bridge now has sibling repeat and
spool helpers, no retry/backoff -- ntfy re-delivers nothing on a command
failure, so a failed message is spooled to the state dir and replayed (oldest
first, through the same correlation-key dedup) before the next message is
handled. After NTFY_ZAMMAD_FAILURE_THRESHOLD consecutive failures it also
pages `keystone` directly.
"""

import importlib
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

# ntfy executes this hook through its shebang; add the deployed sibling-module directory explicitly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ntfy_zammad_repeat = importlib.import_module("ntfy_zammad_repeat")
ntfy_zammad_spool = importlib.import_module("ntfy_zammad_spool")

MANAGED_TAG = "ntfy-zammad-managed"


def env(key, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def parse_tags(raw):
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def should_skip(tags):
    return "no-zammad" in tags


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
        env(
            "NTFY_ZAMMAD_REPEAT_INTERVAL_SECONDS",
            str(ntfy_zammad_repeat.DEFAULT_REPEAT_INTERVAL_SECONDS),
        )
    )
    if repeat_interval < 0:
        raise ValueError("NTFY_ZAMMAD_REPEAT_INTERVAL_SECONDS must be non-negative")

    key = ntfy_zammad_repeat.correlation_key(topic, title)
    existing = ntfy_zammad_repeat.find_ticket(zammad_base, zammad_token, key, zammad_call)
    records, record = ntfy_zammad_repeat.load_repeat_record(state_dir, key)
    now = time.time()
    current_state = ntfy_zammad_repeat.alert_state(tags, priority)

    if ntfy_zammad_repeat.handle_existing(
        zammad_base, zammad_token, state_dir, records, key, record, current_state,
        now, repeat_interval, existing, message, tags, priority,
        bridge_opened_ticket, zammad_call,
    ):
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
        payload=new_ticket(
            key, summary, group,
            ntfy_zammad_repeat.note(message, tags, priority), me["id"],
        ),
        method="POST",
    )
    if isinstance(created, dict) and created.get("id") is not None:
        zammad_call(
            zammad_base, zammad_token, "tags/add",
            payload={"item": MANAGED_TAG, "object": "Ticket", "o_id": created["id"]},
            method="POST",
        )
    ntfy_zammad_repeat.remember_article(state_dir, records, key, current_state, now)


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

    assert (
        ntfy_zammad_repeat.correlation_key("network", "WAN down")
        == "fk:ntfy:network:WAN down"
    )
    assert should_skip(["no-zammad"]) is True
    assert should_skip(["high"]) is False
    assert ntfy_zammad_repeat.is_resolved(["resolved"]) is True
    assert ntfy_zammad_repeat.is_resolved(["white_check_mark", "info"]) is True
    assert ntfy_zammad_repeat.is_resolved(["high"]) is False
    assert parse_tags(" a, b ,,c") == ["a", "b", "c"]
    assert ntfy_zammad_repeat.first_ticket([]) is None
    assert ntfy_zammad_repeat.first_ticket({}) is None
    assert ntfy_zammad_repeat.first_ticket({"tickets": []}) is None
    assert (ntfy_zammad_repeat.first_ticket([{"id": 7, "title": "t"}]) or {})["id"] == 7
    assert ntfy_zammad_repeat.first_ticket({"tickets": [9], "assets": {}}) == {"id": 9}
    t = new_ticket("fk:ntfy:x:y", "s", "Incidents", {"body": "b"}, 42)
    assert t["customer_id"] == 42 and t["title"] == "fk:ntfy:x:y — s"
    n = ntfy_zammad_repeat.note("body text", ["a", "b"])
    assert n["internal"] is True and "body text" in n["body"] and "a, b" in n["body"]

    # Lucene phrase escaping: :, (, ), AND/OR/NOT are literal once inside a
    # correctly-escaped quoted phrase; only backslash and " can break out,
    # so escaping just those two keeps the hostile value INSIDE one phrase.
    assert ntfy_zammad_repeat.escape_lucene_phrase('a\\b"c') == 'a\\\\b\\"c'
    hostile = 'net" OR state.name:closed AND title:"x (foo:bar) NOT y'
    hostile_key = ntfy_zammad_repeat.correlation_key("topic", hostile)
    query = ntfy_zammad_repeat.build_search_query(hostile_key)
    assert query == 'title:"%s" AND state.name:(new OR open)' % ntfy_zammad_repeat.escape_lucene_phrase(
        hostile_key
    )

    # Self-alert must fire exactly once when crossing the threshold, not on
    # every failure afterward, and a success must reset the counter so the
    # NEXT outage can alert again.
    with tempfile.TemporaryDirectory() as state_dir:
        fired = []
        orig_publish = ntfy_zammad_spool.publish_self_alert
        ntfy_zammad_spool.publish_self_alert = lambda *a, **k: fired.append(1)
        try:
            for _ in range(5):
                ntfy_zammad_spool.record_failure(state_dir, 3, "http://ntfy", "keystone")
            assert fired == [1], "self-alert must fire exactly once crossing threshold"
            ntfy_zammad_spool.clear_failures(state_dir)
            for _ in range(3):
                ntfy_zammad_spool.record_failure(state_dir, 3, "http://ntfy", "keystone")
            assert fired == [1, 1], "counter reset must allow a second alert on the next outage"
        finally:
            ntfy_zammad_spool.publish_self_alert = orig_publish

    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    _state_dir = env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad")
    _msg = current_message()
    try:
        ntfy_zammad_spool.replay_spool(_state_dir, handle)
        handle(_msg)
    except urllib.error.HTTPError as exc:
        sys.stderr.write(
            "ERROR Zammad HTTP %s %s: %s\n" % (exc.code, exc.url, exc.read().decode()[:500])
        )
        if ntfy_zammad_spool.is_transient(exc) and not should_skip(_msg["tags"]):
            ntfy_zammad_spool.spool_message(_state_dir, _msg)
        ntfy_zammad_spool.record_failure(
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
        if ntfy_zammad_spool.is_transient(exc) and not should_skip(_msg["tags"]):
            ntfy_zammad_spool.spool_message(_state_dir, _msg)
        ntfy_zammad_spool.record_failure(
            env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad"),
            int(env("NTFY_ZAMMAD_FAILURE_THRESHOLD", "3")),
            env("NTFY_BASE_URL", ""),
            env("NTFY_ZAMMAD_KEYSTONE_TOPIC", ""),
        )
        sys.exit(1)
    else:
        ntfy_zammad_spool.clear_failures(env("NTFY_ZAMMAD_STATE_DIR", "/var/lib/ntfy-zammad"))
