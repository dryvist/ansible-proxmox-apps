# openhands

The OpenHands role. It creates the service user and the state directory and
installs Agent Canvas with its runtimes. The service comes in a later PR, and
`openhands_service_enabled` stays `false` until then.

## What will run

Three OpenHands components, each pinned by a version in `defaults/main.yml`:

- **Agent Canvas**: the web frontend, installed now as a global npm package
  through the site's npm cache.
- **Agent server**: the backend an agent session talks to.
- **Automation server**: the headless automation entry point.

The runtimes Canvas needs are installed with it: a pinned, checksum-verified
Node.js release (major `openhands_node_major`, exact version
`openhands_node_version`) and the uv toolchain (`openhands_uv_version`, pip
installed into its own venv and exposed as `uv`/`uvx` on the default PATH).
Both package fetches resolve through the site's package caches; the role
asserts the cache URLs exist and never fetches from the public registries.

Each conversation runs in its own container, capped by
`openhands_conversation_memory_limit`, `openhands_conversation_cpus` and
`openhands_conversation_pids_limit`. The web frontend will listen on
`openhands_port`.

## State

`openhands_state_dir` is both the state directory and the home of the
`openhands_user` service user. The role creates it with mode `0750`, owned by
that user, who is a member of the `docker` group so it can start
conversation containers. The role reads no secret facts.

The install writes the uv configuration the service user reads into
`.config/uv/uv.toml` under that state directory; it points uv's default
index at the site's PyPI cache, so the launcher's `uvx` calls fetch through
the cache too.

## Installation

Program files live under `openhands_install_dir`: the Node.js runtime, the
Canvas npm tree and the uv venv. `uv` and `uvx` are exposed on the default
PATH for the service user.

Included via the `Deploy OpenHands` play in `playbooks/site.yml`, in the
site's isolated-failure shape. Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags openhands --diff
```

## Usage

Override the defaults in `defaults/main.yml` through inventory group
variables.
