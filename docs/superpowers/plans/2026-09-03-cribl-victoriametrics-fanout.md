# Cribl → VictoriaMetrics Fan-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fan every Prometheus keep-list sample already received by Cribl Stream `in_prometheus_rw` into VictoriaMetrics as well as Splunk, so Gatus (and siblings) are queryable from both stores.

**Architecture:** Dual `connections[]` on `prometheus_rw:in_prometheus_rw`. Existing leg keeps `pipeline: prometheus_to_netmon` → `splunk_hec`. New leg has **no** Splunk-stamp pipeline → new `type: prometheus` output `victoriametrics_rw` posting to `http://grafana.<domain>:<victoriametrics_port>/api/v1/write`.

**Tech Stack:** Ansible (`roles/cribl_stream`), Cribl Stream YAML configs, VictoriaMetrics remote_write, existing template-render tests under `tests/template_render/`.

**Spec:** `docs/superpowers/specs/2026-09-03-cribl-victoriametrics-fanout-design.md`

## Global Constraints

- Cribl must not scrape `/metrics` — Prometheus remains the scraper
- Never hardcode guest IPs in new code; URL uses FQDN + `service_ports.victoriametrics`
- Do not attach `prometheus_to_netmon` to the VictoriaMetrics connection
- No tofu/firewall changes (`:8428` already open from internal)
- Work in worktree: `/Users/jevans/git/public/homelab/ansible-proxmox-apps/.worktrees/estate-health-uis`
- Doc touch for tofu lives under `/Users/jevans/git/public/homelab/tofu-proxmox` (checkout/worktree as needed; PR already merged for estate-health — use a small follow-up branch or amend docs on `develop`)

## File map

| File | Responsibility |
| --- | --- |
| `roles/cribl_stream/defaults/main.yml` | `cribl_stream_victoriametrics_rw_url` default |
| `roles/cribl_stream/templates/outputs.yml.j2` | `victoriametrics_rw` destination |
| `roles/cribl_stream/templates/inputs.yml.j2` | Second connection on `in_prometheus_rw` |
| `tests/template_render/verify/cribl_stream.yml` | Fixture vars for the new URL |
| `tests/template_render/verify/cribl_stream/assertions_inputs.yml` | Assert output + dual connections |
| `tofu-proxmox/docs/AI_OBSERVABILITY.md` | Contract sentence for dual fan-out |

---

### Task 1: Failing template-render assertions

**Files:**
- Modify: `tests/template_render/verify/cribl_stream.yml`
- Modify: `tests/template_render/verify/cribl_stream/assertions_inputs.yml`

**Interfaces:**
- Consumes: rendered `_cribl_stream_inputs`, `_cribl_stream_outputs_pi` (existing decode vars from `render_and_decode.yml`)
- Produces: failing asserts that require `victoriametrics_rw` + dual connections

- [ ] **Step 1: Add fixture URL var to the render play**

In `tests/template_render/verify/cribl_stream.yml`, after the existing `cribl_stream_prometheus_rw_api_path` vars, add:

```yaml
    cribl_stream_victoriametrics_rw_url: "http://grafana.example.invalid:8428/api/v1/write"
```

- [ ] **Step 2: Extend the prometheus_rw assert and add a VM output assert**

Replace the existing task named `Assert prometheus_rw input is present on port 9201 with prometheusAPI and prometheus_to_netmon pipeline` in `assertions_inputs.yml` with:

```yaml
- name: Assert prometheus_rw input fans to Splunk and VictoriaMetrics
  ansible.builtin.assert:
    that:
      - "'type: prometheus_rw' in _cribl_stream_inputs"
      - "'port: 9201' in _cribl_stream_inputs"
      - "'prometheusAPI: /api/v1/write' in _cribl_stream_inputs"
      - "'pipeline: prometheus_to_netmon' in _cribl_stream_inputs"
      - "'output: splunk_hec' in _cribl_stream_inputs"
      - "'output: victoriametrics_rw' in _cribl_stream_inputs"
    fail_msg: >-
      inputs.yml.j2 must include prometheus_rw on port 9201 with
      prometheusAPI: /api/v1/write, connected to BOTH
      (prometheus_to_netmon → splunk_hec) and (victoriametrics_rw with no
      Splunk-stamp pipeline)

- name: Assert victoriametrics_rw Prometheus remote_write output renders
  ansible.builtin.assert:
    that:
      - "'victoriametrics_rw:' in _cribl_stream_outputs_pi"
      - "'type: prometheus' in _cribl_stream_outputs_pi"
      - "'url: http://grafana.example.invalid:8428/api/v1/write' in _cribl_stream_outputs_pi"
    fail_msg: >-
      outputs.yml.j2 must define victoriametrics_rw as type: prometheus
      targeting the fixture URL (FQDN + victoriametrics port + /api/v1/write)
```

Also update the final debug `msg` in `cribl_stream.yml` to mention dual fan-out:

```yaml
          - inputs.yml.j2: prometheus_rw (9201) → splunk_hec + victoriametrics_rw
```

- [ ] **Step 3: Run the render test and confirm it fails**

```bash
cd /Users/jevans/git/public/homelab/ansible-proxmox-apps/.worktrees/estate-health-uis
ansible-playbook tests/template_render/verify/cribl_stream.yml
```

Expected: FAIL on the new `victoriametrics_rw` / dual-connection asserts.

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/template_render/verify/cribl_stream.yml \
        tests/template_render/verify/cribl_stream/assertions_inputs.yml
git commit -m "$(cat <<'EOF'
test(cribl_stream): require VictoriaMetrics remote_write fan-out

Failing asserts for dual in_prometheus_rw connections and the
victoriametrics_rw prometheus destination.

EOF
)"
```

---

### Task 2: Implement Stream output + dual connection

**Files:**
- Modify: `roles/cribl_stream/defaults/main.yml`
- Modify: `roles/cribl_stream/templates/outputs.yml.j2`
- Modify: `roles/cribl_stream/templates/inputs.yml.j2`

**Interfaces:**
- Consumes: `PROXMOX_SUBDOMAIN`, `tofu_data.constants.service_ports.victoriametrics` (or fixture override)
- Produces: `cribl_stream_victoriametrics_rw_url`, output id `victoriametrics_rw`, second input connection

- [ ] **Step 1: Add default URL after the prometheus_rw path defaults**

In `roles/cribl_stream/defaults/main.yml`, immediately after `cribl_stream_prometheus_rw_api_path: /api/v1/write`, insert:

```yaml
# VictoriaMetrics remote_write destination (grafana guest, internal-only).
# FQDN + service_ports.victoriametrics — never a guest IP. Override in tests.
cribl_stream_victoriametrics_rw_url: >-
  http://grafana.{{ lookup('env', 'PROXMOX_SUBDOMAIN')
  | default(undef(), true)
  | mandatory('PROXMOX_SUBDOMAIN required for victoriametrics_rw') }}:{{
     hostvars['localhost']['tofu_data']['constants']['service_ports']['victoriametrics']
     | default(hostvars[inventory_hostname]['tofu_data']['constants']['service_ports']['victoriametrics'] | default(omit))
     | mandatory('tofu_data.constants.service_ports.victoriametrics missing')
  }}/api/v1/write
```

**Simpler form preferred if `grafana_hostname` / port vars are already in scope on Stream hosts** — use this instead if inventory already exposes them cleanly (match sibling roles):

```yaml
cribl_stream_victoriametrics_rw_url: >-
  http://grafana.{{ lookup('env', 'PROXMOX_SUBDOMAIN')
  | default(undef(), true)
  | mandatory('PROXMOX_SUBDOMAIN required for victoriametrics_rw') }}:{{
     (hostvars['localhost']['tofu_data'] | default({})).constants.service_ports.victoriametrics
     | default((tofu_data | default({})).constants.service_ports.victoriametrics)
     | mandatory('service_ports.victoriametrics required for victoriametrics_rw')
  }}/api/v1/write
```

Pick **one** of the two blocks above when implementing; the fixture override in Task 1 must win in tests so live `tofu_data` is not required for template-render.

- [ ] **Step 2: Append the Prometheus destination to outputs.yml.j2**

After the `langfuse_otlp:` block (end of file), append:

```yaml

  # VictoriaMetrics remote_write — fan-out sibling of the Splunk leg on
  # in_prometheus_rw. Receives the same keep-list samples Prometheus already
  # posts to Stream (including job=gatus). Internal-only; no Traefik.
  victoriametrics_rw:
    id: victoriametrics_rw
    type: prometheus
    disabled: false
    url: "{{ cribl_stream_victoriametrics_rw_url }}"
    concurrency: 5
    maxPayloadSizeKB: 4096
    maxPayloadEvents: 0
    rejectUnauthorized: false
    timeoutSec: 30
    flushPeriodSec: 1
    useRoundRobinDns: false
    failedRequestLoggingMode: none
    safeHeaders: []
    onBackpressure: queue
    pqEnabled: true
    pqPath: "$CRIBL_HOME/state/queues"
    pqMaxFileSize: "1 GB"
    pqMaxSize: "10 GB"
    pqCompress: none
```

- [ ] **Step 3: Dual-connect `in_prometheus_rw` in inputs.yml.j2**

Replace the existing `connections:` list under `prometheus_rw:in_prometheus_rw` with:

```yaml
    connections:
      - output: splunk_hec
        pipeline: prometheus_to_netmon
      - output: victoriametrics_rw
```

Do **not** set `pipeline:` on the VictoriaMetrics connection.

- [ ] **Step 4: Re-run the render test**

```bash
cd /Users/jevans/git/public/homelab/ansible-proxmox-apps/.worktrees/estate-health-uis
ansible-playbook tests/template_render/verify/cribl_stream.yml
```

Expected: PASS (all cribl_stream template assertions).

- [ ] **Step 5: Commit**

```bash
git add roles/cribl_stream/defaults/main.yml \
        roles/cribl_stream/templates/outputs.yml.j2 \
        roles/cribl_stream/templates/inputs.yml.j2
git commit -m "$(cat <<'EOF'
feat(cribl_stream): fan Prometheus remote_write to VictoriaMetrics

Dual in_prometheus_rw connections: keep Splunk via prometheus_to_netmon,
add native prometheus destination to grafana:victoriametrics /api/v1/write.

EOF
)"
```

---

### Task 3: Contract docs

**Files:**
- Modify: `/Users/jevans/git/public/homelab/tofu-proxmox/docs/AI_OBSERVABILITY.md` (or the estate-health worktree copy if still present; prefer the live repo `develop` / a short docs branch)

**Interfaces:**
- Consumes: approved design wording
- Produces: docs that match runtime fan-out

- [ ] **Step 1: Update the data-flow bullet**

Change step 2 under `## Data flow (what, not where)` from:

```markdown
2. The stream pipeline routes metrics onward as Prometheus `remote_write`
   into VictoriaMetrics, and usage events into the log platform.
```

to:

```markdown
2. Cribl Stream receives Prometheus `remote_write` on `in_prometheus_rw` and
   fans the same keep-list samples to Splunk (`prometheus_to_netmon` → HEC)
   and to VictoriaMetrics (`victoriametrics_rw` → `/api/v1/write` on the
   grafana guest). Usage events still go to the log platform.
```

- [ ] **Step 2: Commit in the tofu-proxmox repo**

```bash
cd /Users/jevans/git/public/homelab/tofu-proxmox
git switch -c docs/cribl-vm-fanout develop   # or sync-main first if needed
git add docs/AI_OBSERVABILITY.md
git commit -m "$(cat <<'EOF'
docs: Stream fans Prometheus metrics to Splunk and VictoriaMetrics

EOF
)"
```

(Create PR later if that is the repo’s normal docs path; not required to finish the Ansible change.)

---

### Task 4: Converge smoke (manual / operator)

**Files:** none (runtime)

- [ ] **Step 1: Converge Stream**

```bash
cd /Users/jevans/git/public/homelab/ansible-proxmox-apps/.worktrees/estate-health-uis
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags cribl_stream --limit cribl_stream_group
```

(Use the estate’s actual site play / tag names if `cribl_stream` differs — confirm with `rg 'cribl_stream' playbooks/`.)

- [ ] **Step 2: Confirm both destinations**

- Stream UI / destination health: `victoriametrics_rw` not failing
- VictoriaMetrics: `curl -sG 'http://grafana.<domain>:8428/api/v1/query' --data-urlencode 'query=up{job="gatus"}'` (or equivalent) returns series once Gatus scrape + remote_write have run
- Splunk unchanged: `index=netmon_metrics sourcetype=prometheus:metrics job=gatus` still receives events

Do not commit runtime evidence.

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Dual `in_prometheus_rw` connections | Task 2 |
| `victoriametrics_rw` `type: prometheus` | Task 2 |
| FQDN + `service_ports.victoriametrics` | Task 2 defaults |
| No `prometheus_to_netmon` on VM leg | Task 2 inputs |
| Template-render assertions | Task 1 |
| AI_OBSERVABILITY.md sentence | Task 3 |
| No firewall/tofu guest changes | — (explicit non-goal) |
| Post-converge verify Splunk + VM | Task 4 |
