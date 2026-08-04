# cribl_edge_pipelines

Own the Cribl Edge syslog pipeline in version control, including its
event-reduction stages.

## Purpose

The Edge syslog pipeline sets index, sourcetype and host for every syslog
family, then reduces the volume that no query would ever ask for before the
events reach the indexer.

Reduction is deliberately narrow. It applies to two behaviours only:

1. **Service-discovery beacons that were permitted.** Endpoints announce
   themselves on well-known discovery ports continuously. The information is
   "this endpoint beaconed N times in this window", not N copies of the
   beacon. These are rolled up into one counted event per endpoint, port,
   protocol and rule per window. Blocked discovery attempts are excluded and
   pass through whole.
2. **Log-forwarder self-reports.** A forwarder that cannot reach its
   destination re-reports the same failure on every retry. The first report
   in each window passes; the identical repeats behind it are dropped.

Everything else is untouched: every denied or rejected packet, every
authentication and audit record, every low-volume source, and every event
that is not one of the two behaviours above.

## Detectability guarantees

These hold by construction, not by convention:

- **The first occurrence always survives.** Suppression allows `N` events per
  key per window before dropping anything, so a failure that has just started
  is never the one that gets dropped.
- **A source going quiet stays visible.** Rollup emits a counted event per
  window while traffic flows, so the count falling to zero — or the events
  stopping — is itself observable. Reduction never replaces a stream with
  silence.
- **Grouping identity is preserved.** The rollup groups on rule, verdict,
  protocol, source endpoint and destination port, so every field you would
  later group or alert on survives in the aggregate.
- **Exceptional events keep full fidelity.** The rollup filter requires the
  permit verdict; anything denied or rejected bypasses reduction entirely.

## Requirements

- Cribl Edge installed, running in Edge mode (`cribl mode-edge`), reading
  config from `/opt/cribl/local/edge`.
- The syslog inputs already present on the node, each connected to the
  `syslog` pipeline.

## Role Variables

All variables in `defaults/main.yml` are user-configurable.

### Key Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `cribl_edge_pipelines_rollup_ports` | discovery port list | Destination ports whose permitted traffic is rolled up |
| `cribl_edge_pipelines_rollup_window` | `60s` | Tumbling window for the rollup |
| `cribl_edge_pipelines_rollup_sourcetype` | `ubiquiti:firewall:rollup` | Sourcetype the counted events land under |
| `cribl_edge_pipelines_suppress_period_sec` | `600` | Suppression window for forwarder self-reports |
| `cribl_edge_pipelines_suppress_allow` | `1` | Events allowed per key per window before dropping |

Set `cribl_edge_pipelines_rollup_ports` to an empty list to disable the
rollup without removing the role.

## Installation

The role ships with this repository; no external collection is needed. Add it
to the Edge play alongside the install role that provisions Cribl Edge itself:

```yaml
- name: Configure Cribl Edge
  hosts: cribl_edge
  roles:
    - cribl_edge_pipelines
```

## Usage

Run the Edge play. The role renders the pipeline and restarts Cribl Edge only
when the rendered content changes, so repeat runs are no-ops.

```bash
ansible-playbook playbooks/site.yml --limit cribl_edge
```

Confirm the reduction is live by comparing counted beacons against raw
packet records for the same window; the rollup sourcetype should carry the
volume and the raw firewall sourcetype should carry only what was not rolled
up.

## Examples

### Basic Deployment

```yaml
- name: Configure Cribl Edge pipelines
  hosts: cribl_edge
  roles:
    - cribl_edge_pipelines
```

### Widen the rollup window

```yaml
- name: Configure Cribl Edge pipelines
  hosts: cribl_edge
  roles:
    - role: cribl_edge_pipelines
      vars:
        cribl_edge_pipelines_rollup_window: 5m
```

## Querying rolled-up data

Rolled-up events carry `event_count` and land under a distinct sourcetype, so
a raw-event query never silently includes them. To count discovery beacons,
sum `event_count` rather than counting events.

## Tasks

- Create the syslog pipeline directory
- Render the syslog pipeline configuration

## Handlers

- `Restart cribl edge`: Restart the Cribl Edge service
