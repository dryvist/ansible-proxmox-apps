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

## Outgoing requests

Webhooks may target private network addresses. This rests on two assumptions:
webhooks are created only through this repository's automation, and every
Vikunja user is the operator or an agent bot. If either assumption changes,
turn `vikunja_outgoing_requests_allow_non_routable_ips` off or route webhooks
through a proxy (`outgoingrequests.proxyurl`).
