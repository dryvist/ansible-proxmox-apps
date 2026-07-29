# OpenBao voter-health SPL

Reference SPL for the `openbao:voter:health` events shipped by the
`openbao_voter_health` telemetry (see
[`roles/openbao/README.md`](../roles/openbao/README.md#voter-health-scoring)
for the field reference and the keep/demote evidence thresholds these
searches feed). Docs/code only — no dashboards or alerts are provisioned by
this repo; paste these into Splunk (or a saved search / alert) by hand, or
manage them from `ansible-splunk` if/when that repo takes ownership of
OpenBao-specific Splunk content.

## Scorecard: per-voter 7-day and 30-day rollup

```spl
index=openbao sourcetype="openbao:voter:health" earliest=-30d
| eval is_up=if(health_state IN ("active","standby","performance_standby"), 1, 0)
| eval in_7d=if(_time >= relative_time(now(), "-7d"), 1, 0)
| stats
    count as samples_30d,
    sum(is_up) as up_30d,
    sum(eval(in_7d=1)) as samples_7d,
    sum(eval(in_7d=1 AND is_up=1)) as up_7d,
    p95(latency_ms) as p95_latency_ms_30d,
    p95(eval(if(in_7d=1, latency_ms, null()))) as p95_latency_ms_7d,
    avg(raft_lag_ms) as avg_raft_lag_ms,
    max(raft_lag_ms) as max_raft_lag_ms,
    values(health_state) as states_seen
    by voter
| eval uptime_pct_30d=round(up_30d / samples_30d * 100, 2)
| eval uptime_pct_7d=round(up_7d / samples_7d * 100, 2)
| table voter, uptime_pct_7d, uptime_pct_30d, p95_latency_ms_7d, p95_latency_ms_30d, avg_raft_lag_ms, max_raft_lag_ms, states_seen
| sort - uptime_pct_30d
```

## Flap count: state transitions per voter, last 7 days

A "flap" is any change in `health_state` between consecutive samples for the
same voter. High flap count with acceptable average uptime still indicates an
unstable node worth investigating before it indicates a demote-worthy one.

```spl
index=openbao sourcetype="openbao:voter:health" earliest=-7d
| sort 0 voter, _time
| streamstats current=f last(health_state) as prev_state by voter
| eval flapped=if(isnotnull(prev_state) AND prev_state!=health_state, 1, 0)
| stats sum(flapped) as flap_count_7d by voter
| sort - flap_count_7d
```

## Alert: voter unhealthy for more than 24h

Fires when a voter has had **zero** healthy (`active`/`standby`/
`performance_standby`) samples in the trailing 24 hours, i.e. every sample in
that window is `sealed`, `uninitialized`, `unreachable`, or `unknown`. Save
this as an alert on a 15–30 minute cron schedule (matches the ~5 minute
sampling cadence with headroom for a few missed cycles).

```spl
index=openbao sourcetype="openbao:voter:health" earliest=-24h
| eval is_up=if(health_state IN ("active","standby","performance_standby"), 1, 0)
| stats count as samples, sum(is_up) as up_samples, latest(health_state) as last_state, latest(_time) as last_seen by voter
| where up_samples=0
| eval last_seen_human=strftime(last_seen, "%Y-%m-%d %H:%M:%S %Z")
| table voter, samples, last_state, last_seen_human
```

Trigger condition: `number of results > 0`. Route the alert action per the
existing homelab alert-routing convention (ntfy / Zammad ticket per
[`agentsmd/rules`](https://github.com/dryvist/ai-llm-prompts) — not
duplicated here).

## Latency and lag trend for one voter (drill-down)

```spl
index=openbao sourcetype="openbao:voter:health" voter="<voter-name>" earliest=-7d
| timechart span=1h avg(latency_ms) as avg_latency_ms, p95(latency_ms) as p95_latency_ms, avg(raft_lag_ms) as avg_raft_lag_ms
```
