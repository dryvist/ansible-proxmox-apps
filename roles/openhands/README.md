# openhands

Skeleton of the OpenHands role. It creates the service user and the state
directory. The install and the service come in later PRs, and
`openhands_service_enabled` stays `false` until then.

## What will run

Three OpenHands components, each pinned by a version in `defaults/main.yml`:

- **Agent Canvas**: the web frontend.
- **Agent server**: the backend an agent session talks to.
- **Automation server**: the headless automation entry point.

Each conversation runs in its own container, capped by
`openhands_conversation_memory_limit`, `openhands_conversation_cpus` and
`openhands_conversation_pids_limit`. The web frontend will listen on
`openhands_port`.

## State

`openhands_state_dir` is both the state directory and the home of the
`openhands_user` service user. The role creates it with mode `0750`, owned by
that user, who is a member of the `docker` group so it can start
conversation containers. The role reads no secret facts.

## Installation

Included via the `Deploy OpenHands` play in `playbooks/site.yml`, in the
site's isolated-failure shape. Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags openhands --diff
```

## Usage

Override the defaults in `defaults/main.yml` through inventory group
variables.
