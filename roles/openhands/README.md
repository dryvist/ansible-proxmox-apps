# openhands

The OpenHands role. It creates the service user and the state directory,
installs Agent Canvas with its runtimes, and installs and runs the agent
server and the automation service. `openhands_service_enabled` stays `false`
by default: the units install but stay disabled and stopped, and no service
secret is read or rendered until a deployment turns the flag on.

## What runs

Three OpenHands components, each pinned by a version in `defaults/main.yml`:

- **Agent Canvas**: the web frontend, installed as a global npm package
  through the site's npm cache. The service that fronts it comes later.
- **Agent server** (`openhands-agent-server`): the backend an agent session
  talks to. Bound to loopback on `openhands_agent_server_port`.
- **Automation server** (`openhands-automation`): the headless automation
  entry point, run in local agent-server mode — every automation run
  dispatches to the agent server on the same host instead of a cloud
  sandbox. Bound to loopback on `openhands_automation_port`.

The two Python services install into their own venv through the site's PyPI
cache (`uv pip install`, both pinned in `defaults/main.yml`; the automation
package itself pins the matching `openhands-sdk` release). The venv uses a
uv-managed CPython 3.12 interpreter downloaded through the published raw
release cache. The units use the shared systemd hardening template, restart on
failure, and run as `openhands_user` with the state directory as both home and
working directory. When enabled, the role waits for each service and verifies
its `/health` endpoint. Agent conversations use Docker with the configured
memory, CPU and process limits.

## The agents' LLM

The agent server reaches the LiteLLM router at `openhands_router_base_url` and
asks for the router role alias `openhands_router_model`. Both reach the
services in a root-owned `0600` environment file rendered only while the
service is enabled. The router key comes from the root-only file named by
`openhands_router_key_file`; systemd loads it as a credential and the agent
server reads it at startup.

## State

`openhands_state_dir` is both the state directory and the home of the
`openhands_user` service user. The role creates it with mode `0750`, owned by
that user, who is a member of the `docker` group so it can start
conversation containers.

The role generates each service secret only when its backing file is absent
and preserves existing values. The automation keeps its SQLite database
under `openhands_automation_db_path` (it migrates on startup) and its per-run
workspaces under `openhands_automation_workspace_base`.

The install writes the uv configuration the service user reads into
`.config/uv/uv.toml` under that state directory; it points uv's default
index at the site's PyPI cache, so the launcher's `uvx` calls fetch through
the cache too.

## Installation

Program files live under `openhands_install_dir`: the Node.js runtime, the
Canvas npm tree, the uv venv and the services' venv. `uv` and `uvx` are
exposed on the default PATH for the service user.

Included via the `Deploy OpenHands` play in `playbooks/site.yml`, in the
site's isolated-failure shape. Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags openhands --diff
```

## Usage

Override the defaults in `defaults/main.yml` through inventory group
variables.
