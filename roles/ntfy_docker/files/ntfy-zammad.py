#!/usr/bin/env python3
"""ntfy CLI `command:` hook: open/append/close a Zammad ticket for one ntfy
message (see roles/ntfy_docker templates/client.yml.j2).

Contract: ntfy's own CLI runs this once per matching message (already
priority-filtered by client.yml's `if:` clause) with the message fields as
env vars (NTFY_TOPIC, NTFY_TITLE, NTFY_MESSAGE, NTFY_TAGS, NTFY_ID -- see
https://docs.ntfy.sh/subscribe/cli/), plus the connection settings from
/etc/ntfy-zammad/ntfy-zammad.env (deployed alongside this script, inherited
because both run under the same systemd service).

Dedup is by "topic|title" (the correlation key): an open ticket with that
exact title gets an appended article instead of a new ticket. A `resolved` or
`white_check_mark` tag closes the matching open ticket. A `no-zammad` tag
skips ticket action entirely -- this is how the subscriber's OWN failure
alert (published back to the keystone topic below) avoids opening a ticket
about itself.

Adapted from splunk-homelab-alerts/bin/zammad.py's find-or-append pattern
(same estate, same Zammad instance) -- title-search dedup, stdlib-only
urllib, non-zero exit on failure.

ponytail: stdlib only, one file, no retry/backoff -- ntfy re-delivers nothing
on a command failure, so a failed message is spooled to the state dir and
replayed (oldest first, through the same correlation-key dedup) before the
next message is handled. After NTFY_ZAMMAD_FAILURE_THRESHOLD consecutive
failures it also pages `keystone` directly.
"""

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

OPEN_STATES = ("new", "open")
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


def note(message, tags):
    lines = [message or ""]
    if tags:
        lines.append("")
        lines.append("Tags: %s" % ", ".join(tags))
    return {"body": "\n".join(lines), "type": "note", "internal": True}


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
    }


def handle(msg):
    topic, title, message, tags = msg["topic"], msg["title"], msg["message"], msg["tags"]

    if should_skip(tags):
        return

    zammad_base = env("ZAMMAD_API_URL")
    zammad_token = env("ZAMMAD_API_TOKEN")
    if not zammad_base or not zammad_token:
        raise RuntimeError("ZAMMAD_API_URL/ZAMMAD_API_TOKEN not set")

    key = correlation_key(topic, title)
    existing = find_ticket(zammad_base, zammad_token, key)

    if is_resolved(tags):
        if existing:
            zammad_call(
                zammad_base, zammad_token, "tickets/%s" % existing["id"],
                payload={"state": "closed", "article": note(message, tags)}, method="PUT",
            )
        return

    if existing:
        zammad_call(
            zammad_base, zammad_token, "tickets/%s" % existing["id"],
            payload={"article": note(message, tags)}, method="PUT",
        )
        return

    groups = json.loads(env("NTFY_ZAMMAD_TOPIC_GROUPS_JSON", "{}"))
    group = groups.get(topic, "Incidents")
    # "fk:... — <human summary>", same layout as every other source: the
    # fk: token stays the exact-phrase dedup key, the summary after the dash
    # is only for a human reading the ticket list.
    summary = message.splitlines()[0] if message else title
    me = zammad_call(zammad_base, zammad_token, "users/me")
    zammad_call(
        zammad_base, zammad_token, "tickets",
        payload=new_ticket(key, summary, group, note(message, tags), me["id"]),
        method="POST",
    )


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
    import email.message
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

    # Spool: a failed post spools, the next success replays it oldest first,
    # and a replayed key with an open ticket appends instead of re-creating.
    os.environ.update({"ZAMMAD_API_URL": "http://zammad.test/api/v1", "ZAMMAD_API_TOKEN": "t"})
    tickets, calls, zammad = {}, [], {"down": True}

    def fake_call(base, token, path, payload=None, method=None):
        if zammad["down"]:
            raise urllib.error.URLError("no available server")
        calls.append((method, path))
        if path.startswith("tickets/search"):
            want = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["query"][0]
            return [{"id": i} for i, t in tickets.items() if want.startswith('title:"%s" ' % escape_lucene_phrase(t))]
        if path == "users/me":
            return {"id": 1}
        if method == "POST" and path == "tickets":
            tickets[len(tickets) + 1] = (payload or {})["title"].split(" — ")[0]
        return {}

    def read_json(path):
        with open(path) as f:
            return json.load(f)

    no_headers = email.message.Message()
    orig_call = globals()["zammad_call"]
    globals()["zammad_call"] = fake_call
    msg = {"topic": "network", "title": "WAN down", "message": "m", "tags": ["high"]}
    try:
        with tempfile.TemporaryDirectory() as state_dir:
            try:
                handle(msg)
            except urllib.error.URLError:
                spool_message(state_dir, msg)
            spooled = os.listdir(spool_dir(state_dir))
            assert len(spooled) == 1
            assert os.stat(os.path.join(spool_dir(state_dir), spooled[0])).st_mode & 0o777 == 0o600
            assert "t" not in read_json(os.path.join(spool_dir(state_dir), spooled[0])).values()

            # Still down: replay fails and keeps the file.
            try:
                replay_spool(state_dir, handle)
            except urllib.error.URLError:
                pass
            assert len(os.listdir(spool_dir(state_dir))) == 1

            zammad["down"] = False
            replay_spool(state_dir, handle)
            assert os.listdir(spool_dir(state_dir)) == []
            assert list(tickets.values()) == ["fk:ntfy:network:WAN down"]

            # The same key again (a second replay or a live repeat) appends.
            spool_message(state_dir, msg)
            replay_spool(state_dir, handle)
            assert len(tickets) == 1 and ("PUT", "tickets/1") in calls

            # A spooled 4xx is dropped, not retried forever.
            spool_message(state_dir, dict(msg, title="bad"))

            def reject(m):
                raise urllib.error.HTTPError("u", 422, "bad", no_headers, None)

            replay_spool(state_dir, reject)
            assert os.listdir(spool_dir(state_dir)) == []
            assert is_transient(urllib.error.URLError("x"))
            assert is_transient(urllib.error.HTTPError("u", 503, "x", no_headers, None))
            assert not is_transient(urllib.error.HTTPError("u", 422, "x", no_headers, None))
            assert not is_transient(ValueError("x"))

            # The cap drops the oldest file.
            for i in range(3):
                spool_message(state_dir, dict(msg, title="t%d" % i), max_files=2)
            left = [read_json(os.path.join(spool_dir(state_dir), n))["title"]
                    for n in sorted(os.listdir(spool_dir(state_dir)))]
            assert left == ["t1", "t2"], left
    finally:
        globals()["zammad_call"] = orig_call

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
