"""Incremental alert grouping with durable fingerprints and checkpointing."""

import hashlib
import json
import sqlite3
import time
from collections import defaultdict
from urllib.parse import quote

from splunktriage.client import Client

CRON = "3,13,23,33,43,53 * * * *"


def message(name, events, draft, client):
    summary = draft["what_fired"]
    cause = draft["likely_cause"]
    if not all(isinstance(value, str) and value.strip() for value in (summary, cause)):
        raise ValueError("triage requires summary and cause")
    indices = draft["top_events"]
    if (not isinstance(indices, list) or len(indices) != min(3, len(events))
            or len(set(indices)) != len(indices)
            or any(type(i) is not int or not 0 <= i < len(events) for i in indices)):
        raise ValueError("triage requires top event indices")
    lines = [f"Alert: {name[:200]}", f"What fired: {summary[:500]}",
             f"Likely cause: {cause[:500]}", "Top events:"]
    lines.extend("> " + json.dumps(events[i], ensure_ascii=False)[:600] for i in indices)
    spl = draft.get("next_spl")
    lines.append("Next SPL: " + spl if client.valid_spl(spl)
                 else "Next SPL: unavailable (parser validation failed)")
    return "\n".join(lines)


def run(config, client=None, now=None):
    client = client or Client(config)
    now = time.time() if now is None else now
    with sqlite3.connect(config["state_path"]) as db:
        db.execute("CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY, stamp REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS sent (fingerprint TEXT PRIMARY KEY, stamp REAL)")
        row = db.execute("SELECT stamp FROM checkpoint WHERE id=1").fetchone()
        since = row[0] if row else now - 600
        if row is None:
            db.execute("INSERT INTO checkpoint VALUES (1, ?)", (since,))
            db.commit()
        groups = defaultdict(list)
        for group in client.entries("/services/alerts/fired_alerts"):
            if group["name"] == "-":
                continue
            path = "/services/alerts/fired_alerts/" + quote(group["name"], safe="")
            for alert in client.entries(path):
                stamp = float(alert["content"]["trigger_time"])
                if since <= stamp <= now:
                    groups[group["name"]].append(alert)
        posted = 0
        for name, alerts in groups.items():
            # Per-occurrence fingerprints survive retries and changed batch boundaries.
            pending = []
            for alert in alerts:
                fingerprint = hashlib.sha256(json.dumps(
                    [name, alert["name"], alert["content"]["sid"],
                     alert["content"]["trigger_time"]], sort_keys=True).encode()).hexdigest()
                if not db.execute("SELECT 1 FROM sent WHERE fingerprint=?", (fingerprint,)).fetchone():
                    pending.append((fingerprint, alert))
            if not pending:
                continue
            # One bounded drilldown for the newest occurrence of the group.
            latest = max(pending, key=lambda item: float(item[1]["content"]["trigger_time"]))[1]
            events = client.events(latest)
            draft = client.draft(name, events)
            client.post(message(name, events, draft, client))
            db.executemany("INSERT OR IGNORE INTO sent VALUES (?, ?)",
                           [(fingerprint, now) for fingerprint, _ in pending])
            db.commit()
            posted += 1
        db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1, ?)", (now,))
        db.execute("DELETE FROM sent WHERE stamp < ?", (since - 86400,))
    return {"posted": posted}
