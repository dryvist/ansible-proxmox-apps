# vikunja

Installs and configures [Vikunja](https://vikunja.io), a self-hosted task
manager.

## Installation

Included via the `Configure Vikunja task management` play in
`playbooks/site.yml`. Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags vikunja --diff
```

## Usage

Role defaults live under `defaults/main/`; override them in inventory group
variables. The rendered configuration comes from `templates/config.yml.j2`.

Narrow a run with `--skip-tags` on `vikunja_operator_access`,
`vikunja_agent_access`, `vikunja_mcp_read_access` or
`vikunja_openhands_trigger`, and limit the token
loop to named identities with
`-e '{"vikunja_mcp_token_only_users": ["svc-mcp-clerk"]}'` (empty means all).

## Agent roles

The per-caller roles are `workstation`, `hermes`, `pepper`, `untrusted`,
`machines`, `jobs`, `inbox`, `acceptance`, `triage`, `nightly` and `windows`.
`vikunja_agent_roles_enabled` is the on/off list and defaults to empty. The
`vikunja_agent_project_sets` map names `domain`, `work`, `inbox`, `windows`,
`jobs`, `hermes_board`, `donna_board` and `acceptance`; each list defaults to
empty and inventory supplies integer project IDs through
`VIKUNJA_AGENT_PROJECT_SETS`.

## OpenHands trigger

The role provisions the `openhands` bot for the hand-created trigger project:
it creates the service user, shares the project with it, pre-creates the
`openhands-running`, `openhands-done` and `openhands-failed` status labels as
that user, and mints an `openhands-trigger` API token scoped to reading
tasks, commenting on them, and applying or removing the bot's own labels. The
token is published to OpenBao at `secret/apps/openhands-vikunja`, field
`token`.

The trigger project and the `openhands` trigger label are created by hand,
never by this role; the share is made as the automation account that owns the
project. The project is matched by
`vikunja_openhands_project_id` (set it to empty to skip the share), the
labels by title.

## Read-only tracker account

The role shares every project the read-write automation account owns with the
read-only tracker service account at Read permission. The project list is
derived at converge time from the owner's own project pages, never pinned by
id, so a project moved between parents keeps its explicit grant where an
inherited one would vanish. The share is additive: the owning account keeps
ownership, and no share is ever revoked. The share runs independently of the
operator block, so the tracker keeps its reads even when the human operator
account is not provisioned.

## Tracker conventions

Agents and people follow one set of tracker conventions, and the role keeps
the tracker matching it on every run. Two lists live in
`defaults/main/17-tracker-conventions.yml`: `vikunja_tracker_labels` declares
the labels `epic`, `needs-split`, `needs-info`, `from-untrusted` and
`operator-step`, each with a colour and a description, and
`vikunja_tracker_buckets` declares the kanban buckets `Backlog`, `Ready`,
`In progress`, `Blocked` and `Done` — only `Ready` carries a work-in-progress
limit (10; 0 means no limit). The declared default bucket is `Backlog` and the
declared done bucket is `Done`.

`vikunja_tracker_bucket_renames` maps old titles to declared ones for a board
that still uses them (`To-Do` to `Backlog`, `Doing` to `In progress`): a
bucket still carrying its old title is renamed while the new title does not
exist yet on that view, and never recreated. `vikunja_tracker_board_projects`
lists the project ids the board reconcile runs on — derived from the app-agent
domain project set when one is declared, and empty by default, which leaves
the buckets untouched.

The reconciles create missing labels and buckets, align the declared buckets'
limits and positions so the declared five come first in the declared order,
and point each project's kanban view at the declared default and done buckets
(it fails loudly on a project without a kanban view rather than creating one).
They never delete a label or a bucket: an existing label is left exactly as it
is, and a bucket outside the declarations keeps its place after the declared
five and is never renamed, emptied or deleted.

## Outgoing requests

Webhooks may target private network addresses. This rests on two assumptions:
webhooks are created only through this repository's automation, and every
Vikunja user is the operator or an agent bot. If either assumption changes,
turn `vikunja_outgoing_requests_allow_non_routable_ips` off or route webhooks
through a proxy (`outgoingrequests.proxyurl`).

`vikunja_task_webhooks` declares those webhooks, one row per project, created
as the project's automation owner when absent and never deleted. Each is
signed with the route-only secret `vikunja_task_webhook_secret` (default: env
`VIKUNJA_TASK_WEBHOOK_SECRET`); the run fails if rows are set and the secret is
empty, or if a live webhook's events differ from its row.
