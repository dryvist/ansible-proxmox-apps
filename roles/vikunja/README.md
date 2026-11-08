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

## OpenHands trigger

The role provisions the `openhands` bot for the hand-created trigger project:
it creates the service user, shares the project with it, pre-creates the
`openhands-running`, `openhands-done` and `openhands-failed` status labels as
that user, and mints an `openhands-trigger` API token scoped to reading
tasks, commenting on them, and applying or removing the bot's own labels. The
token is published to OpenBao at `secret/apps/openhands-vikunja`, field
`token`.

The trigger project and the `openhands` trigger label are created by hand
under the operator's account, never by this role. The project is matched by
`vikunja_openhands_project_id` (set it to empty to skip the share), the
labels by title.

## Outgoing requests

Webhooks may target private network addresses. This rests on two assumptions:
webhooks are created only through this repository's automation, and every
Vikunja user is the operator or an agent bot. If either assumption changes,
turn `vikunja_outgoing_requests_allow_non_routable_ips` off or route webhooks
through a proxy (`outgoingrequests.proxyurl`).
