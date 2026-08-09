# Nautobot Export Freshness Alerting

Detects a Nautobot inventory artifact that has stopped being refreshed. This is
the same class of failure as [converge freshness](../CONVERGE_FRESHNESS.md), and
it is handled the same way: this repository owns the **producer**, and the
**consumer** (saved searches) is shipped here as code and lands in
`ansible-splunk`.

## The failure this exists to catch

The export Job publishes the `nautobot-export-v1` artifact. Run purely on a
daily celery-beat schedule, it republishes whatever the ingest jobs last wrote,
of any age, and succeeds every time — so a green export carries no information
about whether the artifact is current. A cache with no invalidation.

Three changes close it, and each covers a hole the others cannot see:

1. **Ingest is now event-based.** `nautobot_build_seed` and
   `nautobot_run_seed_jobs` default on, so every converge — the event that
   resolves a fresh inventory — ingests it.
2. **The export refuses to publish stale content.**
   `export_nautobot.ExportNautobotToS3._assert_ingest_ordering()` raises when no
   ingest has succeeded since the last export. It reasons in the negative
   direction only: absence of an ingest proves staleness. Presence of one never
   proves freshness, and is not treated as if it did.
3. **The converge fails when the schedule is missing.** `tasks/main.yml` asserts
   on the `schedule_export.py` markers rather than letting `SCHEDULE_SKIPPED`
   print and continue.

## Why the schedule is kept

The export is triggered by ingest, not by a clock, and its own docstring says
not to work around the guard by scheduling it. The daily schedule is retained
deliberately, in a different role: **it is the backstop alarm, not the trigger.**

On any day when no converge has ingested, the scheduled export fails loudly
instead of publishing. That failure is the freshness signal. Removing the
schedule would remove the only thing that periodically asks "is this still
fresh?" and return the artifact to failing silently.

This is the one timer in the design, and it is declared as a backstop rather
than a mechanism anything depends on for correctness.

## What must never be done

- **Do not celery-beat schedule the seed jobs.** Bundle assembly is a
  controller-side step (`tasks/seed_bundle.yml`), so a scheduled worker run
  could only replay the bundle already on the guest. That satisfies the ordering
  guard with unchanged content — precisely the silent degradation being fixed.
- **Do not add a bypass flag to the ordering guard.** A skipped export costs one
  run. A published stale artifact misinforms every consumer of it.
- **Do not alarm on the export's exit status alone.** A failing export is the
  system working. The alarm condition is a failing export that *stays* failing,
  which means ingest has stopped.

## Consumer: detections that land in `ansible-splunk`

The Nautobot LXC ships journald to Splunk via `syslog_forwarder` (index `os`),
so the worker's job output is searchable without any new agent.

### Ordering guard firing repeatedly — ingest has stopped

A single failure is expected on any day without a converge. Two or more
consecutive days means ingest itself is broken.

```spl
index=os host=nautobot* "Refusing to publish: no ingest job has succeeded"
| bin _time span=1d
| stats count by _time
| where count > 0
| streamstats count as consecutive_days
| where consecutive_days >= 2
```

### Ingest succeeding while syncing nothing — the case ordering cannot see

The guard checks ordering, not content. A seed job that succeeds against an
unchanged or empty bundle satisfies it. The export logs the newest
`last_updated` across every exported model as `Data as of <ts>`, which is the
honest, row-derived freshness signal. Alarm when that stops advancing while
exports keep passing.

```spl
index=os host=nautobot* "Data as of"
| rex "Data as of (?<data_as_of>\S+)"
| eval age_days = round((now() - strptime(data_as_of, "%Y-%m-%dT%H:%M:%S")) / 86400, 1)
| stats max(age_days) as age_days
| where age_days > 2
```

### Export schedule absent

Covered by the converge assert, not by SPL — the converge fails before it can
report success, so it surfaces through existing converge-failure alerting.

## Where this lands

The saved searches above belong in `ansible-splunk`, which owns Splunk. This
document is the specification; nothing in this repository creates them.
Verifying that they exist is part of closing Phase A, not of merging it.
