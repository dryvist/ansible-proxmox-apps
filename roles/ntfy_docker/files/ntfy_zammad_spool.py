"""Durable message spool for the ntfy-Zammad bridge."""

import json
import os
import sys
import time
import urllib.error
import urllib.request

# ponytail: count cap only; the oldest spooled message is dropped (and logged)
# past it. Add an age cap if a long outage makes stale replays a problem.
SPOOL_MAX = 200


# The spool holds the alert payload only (topic, title, message, tags) -- never
# a credential -- one 0600 JSON file per message, named so a sort is oldest
# first.
def spool_dir(state_dir):
    return os.path.join(state_dir, "spool")


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
