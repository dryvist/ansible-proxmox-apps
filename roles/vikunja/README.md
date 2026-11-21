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
`vikunja_agent_access` or `vikunja_openhands_trigger`, and limit the token
loop to named identities with
`-e '{"vikunja_mcp_token_only_users": ["svc-mcp-clerk"]}'` (empty means all).

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

## Outgoing requests

Webhooks may target private network addresses. This rests on two assumptions:
webhooks are created only through this repository's automation, and every
Vikunja user is the operator or an agent bot. If either assumption changes,
turn `vikunja_outgoing_requests_allow_non_routable_ips` off or route webhooks
through a proxy (`outgoingrequests.proxyurl`).

`vikunja_task_webhooks` declares those webhooks, one row per project, created
as the project's automation owner when absent and never deleted. Each is
signed with the route-only secret from `VIKUNJA_TASK_WEBHOOK_SECRET`; the run
fails if rows are set and the secret is absent, or if a live webhook's events
differ from its row.
