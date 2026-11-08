# openhands

Skeleton for the OpenHands AI agent platform on the `openhands_host`
inventory group (`docker_vms` members carrying the `openhands` tag). This
PR creates the role's identity and state layout only; the install and the
service arrive in later PRs, and `openhands_service_enabled` defaults to
`false` until then.

## What will run here

Three OpenHands components, each pinned by a version in
`defaults/main.yml`:

- **Agent Canvas** — the web frontend.
- **Agent server** — the backend an agent session talks to.
- **Automation server** — the headless automation entry point.

Each conversation runs in its own container, capped by
`openhands_conversation_memory_limit`, `openhands_conversation_cpus` and
`openhands_conversation_pids_limit`. The web frontend publishes on port
`openhands_port` (443) on the host's inventory address.

## State

The `openhands` system user's home and the role's state directory are the
same path, `openhands_state_dir` (`/var/lib/docker/openhands`), which sits
on the guest's dedicated Docker data disk like the rest of this VM class's
persistent data. The directory is created mode `0750` and owned by the
service user, who is a member of the `docker` group so conversation
containers launch through the host daemon.

## Secrets

The OpenHands host is a sandbox guest: it receives empty secret facts by
design (`playbooks/tasks/publish_secret_domain_facts.yml`), and this role
never reads `bao_*_secrets` facts. Credentials will arrive through an
on-host OpenBao AppRole, the same delivery the ci-resolver uses in
`roles/agent_sandbox`.

## Installation

Included via the `Deploy OpenHands` play in `playbooks/site.yml`
(hosts: `openhands_host`), in the site's isolated-failure shape. Converge
just this role:

```sh
ansible-playbook playbooks/site.yml --tags openhands --diff
```

The role currently creates the system user and the state directory; the
container install and the service management are future PRs.
