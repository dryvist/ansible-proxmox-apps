# Design: Cribl Stream metrics fan-out to VictoriaMetrics

**Date:** 2026-09-03  
**Status:** Approved  
**Scope:** Close the AI observability contract gap — Prometheus keep-list metrics (including Gatus) already reach Splunk via Stream; they must also reach VictoriaMetrics via Stream.

## Goal

Every sample Prometheus already `remote_write`s to Cribl Stream must land in **both**:

1. Splunk (existing `prometheus_to_netmon` → `splunk_hec`)
2. VictoriaMetrics on the `grafana` guest (new Cribl `prometheus` destination)

Visualization: Splunk SPL for netmon/host metrics; Grafana dashboards against the `victoriametrics` datasource for the same series (including `job="gatus"`).

## Non-goals

- Cribl scraping Gatus or any other `/metrics` endpoint (forbidden on standalone Edge/Stream; Prometheus remains the scraper)
- Uptime Kuma monitor IaC or Kuma Prometheus metrics
- Healthchecks / ntfy as metric stores
- Changing Edge → Splunk HEC paths
- Dropping Grafana’s optional direct Prometheus datasource (follow-up only)
- Tofu/firewall changes (`victoriametrics` `:8428` already open from internal)

## Current state

```text
exporter /metrics (gatus, blackbox, smokeping, node_exporter, traefik, …)
  → prometheus_stack scrape
  → remote_write → Stream in_prometheus_rw :9201
       → pipeline prometheus_to_netmon
       → splunk_hec  (index netmon_metrics | host_metrics)
```

`AI_OBSERVABILITY.md` already states Stream should `remote_write` into VictoriaMetrics. No such Cribl output exists today.

## Target data path

```text
… → Stream in_prometheus_rw
       ├─ pipeline: prometheus_to_netmon → output: splunk_hec          (unchanged)
       └─ no Splunk-stamp pipeline     → output: victoriametrics_rw  (new)
                                            → http://grafana.<domain>:<victoriametrics_port>/api/v1/write
```

Dual `connections[]` on a single source is the fan-out mechanism. Same samples, two stores, always through Stream.

## Approach (approved)

**Dual connection on `in_prometheus_rw`.** Rejected alternatives:

- Job-filtered fork to VM only for `gatus` — under-delivers “all keep-list metrics”
- Prometheus second `remote_write` straight to VM — bypasses Cribl

## Components

### 1. Cribl output `victoriametrics_rw`

- File: `roles/cribl_stream/templates/outputs.yml.j2`
- `type: prometheus` (Cribl native Prometheus remote_write destination)
- Remote write URL built from inventory FQDN + `tofu_data.constants.service_ports.victoriametrics` (never a hardcoded IP)
- Defaults in `roles/cribl_stream/defaults/main.yml` for host/port/path knobs
- PQ / backpressure: match existing Stream output posture (queue or block consistently with sibling outputs; prefer `onBackpressure: queue` + PQ like `langfuse_otlp` so Splunk path is not stalled by VM)

### 2. Input connection

- File: `roles/cribl_stream/templates/inputs.yml.j2`
- Add second connection on `prometheus_rw:in_prometheus_rw`:
  - `output: victoriametrics_rw`
  - **Omit** `pipeline: prometheus_to_netmon` (that pipeline stamps Splunk `index`/`sourcetype`/`host` and must not run on the VM leg)
- Existing Splunk connection unchanged

### 3. Tests

- Extend `tests/template_render/verify/cribl_stream/` assertions:
  - `victoriametrics_rw` present with `type: prometheus` and expected URL shape
  - `in_prometheus_rw.connections` has both Splunk and VM entries

### 4. Docs

- `tofu-proxmox` `docs/AI_OBSERVABILITY.md`: one sentence that Stream fans Prometheus remote_write to Splunk **and** VictoriaMetrics
- Optional one-liner in `DASHBOARDS.md` health surfaces that Gatus series are in Splunk + VM via Stream

## Error handling / ops

- If VictoriaMetrics is down: Stream PQ on `victoriametrics_rw` absorbs backpressure; Splunk connection continues independently
- If `grafana` guest absent from inventory: fail closed at template render / assert (mandatory port constant), same pattern as other Stream destinations that require a peer
- No silent drop of metric values on the VM path (do not reuse the Splunk `-1` coercion pipeline)

## Verification (post-converge)

1. Template-render assertions green  
2. Converge `cribl_stream`  
3. Stream destination healthy; query VictoriaMetrics for `job="gatus"` (and another keep-list job such as blackbox)  
4. Splunk still receives `index=netmon_metrics sourcetype=prometheus:metrics` for Gatus  

## Implementation boundaries

| In | Out |
| --- | --- |
| `ansible-proxmox-apps` `roles/cribl_stream` + template tests | New guests, firewall rules |
| Short doc touch in `tofu-proxmox` | Grafana dashboard authoring for Gatus (can use existing datasource once series exist) |
| | AutoKuma / Kuma metrics |

## Success criteria

- [ ] Cribl Stream config renders with `victoriametrics_rw` and dual `in_prometheus_rw` connections  
- [ ] After converge, VictoriaMetrics holds keep-list series including Gatus  
- [ ] Splunk path unchanged  
- [ ] Contract docs match runtime  
