# Converge-Freshness Telemetry and Alerting

Detects **stale configuration management**: a host that stopped being
converged, or a host that exists in inventory and has never been converged at
all. Both failure modes are silent today — a guest can drift for months and
nothing in the estate notices, because "no converge happened" produces no
event, no log line and no non-zero exit code anywhere.

This repository owns the **producer** (the events). Splunk is owned by
`ansible-splunk`, so the **consumer** (index + saved searches) is shipped here
as code and lands there — see [Where this lands](#where-this-lands).

## Producer: the `converge_telemetry` callback plugin

`callback_plugins/converge_telemetry.py` posts one batch of events to Splunk
HEC at the end of every `playbooks/site.yml` run.

### Why a callback and not a play

A terminal play in `site.yml` cannot produce a trustworthy success signal:

- Every independent play in `site.yml` is wrapped in `block`/`rescue` for
  failure isolation (issue #672). A host whose play failed is **rescued**, not
  failed, so it stays in the inventory for later plays and a terminal play
  would happily report it as converged.
- A play has no access to per-host result counts. `ok`/`changed`/`failed`/
  `unreachable`/`rescued` only exist in Ansible's end-of-run `stats` object.

The callback reads that `stats` object, so its verdict comes from the
executor's own counters rather than from anything a play asserts about itself.
A host is reported `status=success` only when `failures`, `unreachable` **and**
`rescued` are all zero — `rescued` counts as a failure because the only
`rescue` blocks in this repository are the isolated-failure recorders in
`playbooks/tasks/record_isolated_failure.yml`.

The plugin fires on `v2_playbook_on_stats`, i.e. only after a run finishes. It
cannot fire on playbook start.

### Configuration path

The plugin is enabled globally in `ansible.cfg` but stays **inert** unless the
running playbook publishes its configuration with `ansible.builtin.set_stats`
under the `converge_telemetry` key. Only `playbooks/site.yml` does (Phase
0-telemetry), so validation and utility playbooks emit nothing.

That indirection exists because a callback plugin cannot read `tofu_data`.
The site.yml play derives everything from the OpenTofu constants and hands it
over:

| Published value | Derived from |
| --- | --- |
| `hec_url` | `splunk.{{ tofu_data.domain }}` + `tofu_data.constants.service_ports.splunk_hec` |
| `index` | `converge_telemetry_index` (default `ansible`) |
| `verify_tls` | `converge_telemetry_verify_tls` (default `false`, self-signed lab cert) |
| `timeout` | `converge_telemetry_timeout` (default `10`) |
| `git_sha` | `git rev-parse HEAD` in the converging worktree |
| `roster` | every inventory host except `localhost` |
| `fqdns` | inventory hostname -> `hostname` fact + `tofu_data.domain` |
| `check_mode` | `ansible_check_mode` — see below |

No IP or port literal appears anywhere in the implementation
(`.claude/rules/ip-addressing.md`).

**The HEC token is deliberately not published through `set_stats`.** The
plugin reads `SPLUNK_HEC_TOKEN` from its own environment, so the secret never
enters run stats, callback output, or a stats dump.

### A dry run publishes nothing

`--check` changes nothing on the targets, but Ansible still reports `ok > 0`
for every host the run walked, so `host_status()` would call each one a
success. Publishing that would refresh the freshness clock of a host that was
never converged — a genuinely stale host would read as fresh purely because
someone dry-ran `site.yml`, which is exactly the failure the staleness alert
exists to catch.

The plugin therefore returns before building any event when either signal says
check mode, and one signal alone is enough:

| Signal | Set by | Covers |
| --- | --- | --- |
| `config.check_mode` | site.yml publishes `ansible_check_mode` via `set_stats` | any run, however launched |
| `context.CLIARGS['check']` | the `--check` CLI flag | `ansible-playbook` runs; empty for API-driven runs |

`tests/test_converge_telemetry.py` pins both independently, plus a control
case asserting a non-check run *does* post — so "nothing was published" is
evidence rather than a test that could never fail.

Confirm on any dry run with `-vvv`:

```text
converge_telemetry: check mode; converge freshness not published
```

Off switch: `ANSIBLE_CONVERGE_TELEMETRY_ENABLED=false`.

Failure to publish never fails a converge — the plugin warns and moves on.
Telemetry that can break a converge is worse than no telemetry.

### Events

Both sourcetypes set the HEC `host` field to the guest **FQDN**.

`sourcetype="ansible:converge"` — one per host processed by the run:

```json
{
  "status": "success",
  "host": "<guest>.<domain>",
  "inventory_hostname": "<guest>",
  "playbook": "site.yml",
  "repo": "ansible-proxmox-apps",
  "git_sha": "<40-char sha>",
  "ok": 42, "changed": 3, "skipped": 11,
  "failures": 0, "unreachable": 0, "rescued": 0, "ignored": 0,
  "desired_state_current": false,
  "desired_state_published": "<etag the artifact was rendered from>",
  "desired_state_live": "<etag of desired state right now>"
}
```

The three `desired_state_*` fields answer the link **upstream** of a converge:
was the inventory this run consumed itself built from current desired state?
An apply only re-renders the artifact and a converge only consumes whatever the
artifact says, so a desired-state edit that was never applied makes every
converge confidently wrong rather than failing. `inventory_resolve`
(homelab-contracts) compares the fingerprint stamped into the artifact against
the live desired-state object and publishes the verdict; site.yml passes it
through.

**They are omitted, not defaulted, when the check could not run** (no store
credentials, or an artifact predating schema 2.1.0). A default of `true` would
make the alert green for every converge that never checked — the same silent
hold the alerting exists to catch. `tests/test_converge_telemetry.py` pins the
absent case alongside both verdicts.

`sourcetype="ansible:converge:roster"` — one per **inventory** host, emitted
whether or not that host was targeted by this run. This is what makes orphan
detection possible without shipping a Splunk lookup from a second repository:
the roster is the inventory, published as events by the run that read it.

Failed hosts are emitted too, with `status="failed"`. The alerts filter on
`status=success`; keeping the failures visible means a host stuck failing every
night is distinguishable from a host nothing has tried to converge.

## Index choice

A dedicated **`ansible`** index, not an existing one:

- `os` is the syslog destination for host and native-service logs (see
  `AGENTS.md` pipeline data flow). Converge telemetry is not syslog, has a
  different retention need, and mixing it in would make both harder to alert on.
- `main` is a catch-all with no owner.
- Config-management audit data has its own lifecycle: low volume (one batch per
  converge), long useful retention (the alerts look back 30 days, and a
  compliance question can look back much further).

Override with `converge_telemetry_index` if `ansible-splunk` chooses a
different name; nothing else in this repo hard-codes it.

## Alerts

Both alerts avoid `tstats`: accelerated/indexed-field searches hide dormant
data, and an alert whose entire purpose is to detect **absence** must never be
built on a search path that can silently return nothing.

### Alert 1 — stale converge (no successful converge in 7 days)

```spl
index=ansible sourcetype="ansible:converge" status=success earliest=-30d
| stats max(_time) AS last_converge,
        latest(playbook) AS playbook,
        latest(git_sha) AS git_sha
        BY host
| eval age_days = round((now() - last_converge) / 86400, 1)
| where age_days > 7
| eval last_converge = strftime(last_converge, "%Y-%m-%d %H:%M:%S")
| sort - age_days
| table host, last_converge, age_days, playbook, git_sha
```

Runs hourly, alerts when the result count is greater than zero. The 30-day
look-back bounds the search; a host quiet for longer than that is caught by
alert 2 instead.

### Alert 2 — orphan host (in inventory, no converge at all in 30 days)

```spl
index=ansible
  (sourcetype="ansible:converge:roster"
   OR (sourcetype="ansible:converge" status=success))
  earliest=-30d
| stats max(eval(if(sourcetype=="ansible:converge:roster", _time, null()))) AS last_in_inventory,
        max(eval(if(sourcetype=="ansible:converge", _time, null()))) AS last_converge
        BY host
| where isnotnull(last_in_inventory)
    AND last_in_inventory > relative_time(now(), "-7d")
    AND isnull(last_converge)
| eval last_in_inventory = strftime(last_in_inventory, "%Y-%m-%d %H:%M:%S")
| table host, last_in_inventory
```

Runs daily. The `last_in_inventory > -7d` clause scopes the alert to hosts
**currently** in inventory, so a decommissioned guest ages out on its own
instead of alerting forever. No `join` and no subsearch, so neither the
subsearch result cap nor an autofinalize can silently truncate the answer.

## Where this lands

`docs/splunk/converge_freshness_savedsearches.conf` carries both alerts as
ready-to-deploy `savedsearches.conf` stanzas. They now also ship as code in
`ansible-splunk` (`roles/splunk_docker/templates/savedsearches.conf.j2`,
stanzas `ansible_stale_converge`, `ansible_orphan_host`, `ansible_apply_owed`),
which is what actually deploys them; keep the two in sync or retire this copy
once that has converged.

`ansible-splunk` owns the Splunk deployment, so it must:

1. Create the `ansible` index (`indexes.conf`).
2. Deploy the two stanzas into an app's `local/savedsearches.conf`.
3. Wire `action.*` to whichever notification channel the estate uses (ntfy or
   Zammad); the stanzas ship with actions unset rather than guessing.

Until step 1 exists, this repo's telemetry POSTs are rejected by HEC and the
plugin logs a warning — the converge itself is unaffected.

## Verifying the producer

```bash
# Renders the config from the inventory fixture, builds events, attempts the POST.
TOFU_INVENTORY_PATH=$PWD/tests/inventory_load/tofu_inventory.json \
PROXMOX_SSH_KEY_PATH=/dev/null PROXMOX_DKR_SSH_KEY_PATH=/dev/null \
SPLUNK_HEC_TOKEN=dummy \
  ansible-playbook -i inventory/hosts.yml playbooks/site.yml --limit localhost -vvv \
  | grep converge_telemetry

# Event-shape and success-verdict contracts (no Splunk needed).
python3 tests/test_converge_telemetry.py -v
```
