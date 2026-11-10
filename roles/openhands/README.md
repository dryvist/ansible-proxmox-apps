# openhands

The OpenHands role. It creates the service user and the state directory,
installs Agent Canvas with its runtimes, and runs the Canvas launcher as a
systemd unit. It depends on the shared `docker_engine` role, which installs
Docker. `openhands_service_enabled` stays `false` by default: the launcher unit
installs but stays disabled and stopped, and no service secret is read or
generated until a deployment turns the flag on.

## What runs

Agent Canvas is the npm package `@openhands/agent-canvas`, pinned in
`defaults/main.yml` and installed through the site's npm cache under
`openhands_canvas_dir`. The unit `openhands-canvas.service` runs its launcher
as one process under `openhands_user`, with the Node.js runtime under
`openhands_node_dir`:

- the Canvas web UI,
- the agent server,
- the automation server, in local agent-server mode: automation runs dispatch
  to the agent server on the same host,
- the ingress that serves them.

All of these share one loopback port, `openhands_canvas_port` (8000). The
launcher starts with `--public`, which requires a backend key. The unit
restarts on failure and starts at boot. When enabled, the role waits for the
port and checks that the root path answers with a 2xx, a 3xx or a 401. The
probe never sends the key.

The role also installs the agent server and automation packages into their own
venv through the site's PyPI cache (`uv pip install`, pinned in
`defaults/main.yml`; the automation package pins the matching `openhands-sdk`
release). The venv uses a uv-managed CPython 3.12 downloaded through the
published raw release cache. No unit runs that venv. Agent conversations use
Docker with the configured memory, CPU and process limits, which the launcher
unit sets.

## Keys

Two key values reach the launcher. Neither is written to a unit file or an
environment file:

- `openhands_backend_key_file` names a root-only file holding the backend key
  that `--public` requires. A follow-up OpenBao Agent template fills the file;
  this role does not fetch it. The input check requires the variable when the
  service is enabled.
- `secret-key` and `automation-kv-secret` under `openhands_secrets_dir` are
  generated on the first enable and kept after that. The launcher reads them as
  `OH_SECRET_KEY`, which encrypts stored settings, and `AUTOMATION_KV_SECRET`.

The unit loads all three files with systemd `LoadCredential=` while the service
is enabled. Its `ExecStart` wrapper exports each value into the launcher's
environment and exits if any file is empty.

## The agents' LLM

The LLM profile is set in Canvas under Settings > LLM, or through the backend
API. It uses:

- model `litellm_proxy/<openhands_router_model>`, the LiteLLM router role alias,
- base URL `openhands_router_base_url`,
- the API key from the root-only file named by `openhands_router_key_file`.

The input check requires `openhands_router_key_file` when the service is
enabled. No unit reads that file.

## Variables

- `openhands_canvas_port`: the launcher's port, `8000`.
- `openhands_backend_key_file`: the root-only backend key file, `""` by default.
- `openhands_router_key_file`: the root-only router key file, `""` by default.
- `openhands_router_base_url` and `openhands_router_model`: the router endpoint
  and model alias the LLM profile uses.
- `openhands_secrets_dir`: the root-only directory of the generated secrets.

## State

`openhands_state_dir` is both the state directory and the home of the
`openhands_user` service user. The role creates it with mode `0750`, owned by
that user, who is a member of the `docker` group so it can start conversation
containers. The launcher keeps its settings under `~/.openhands`, which is that
directory.

The role generates each generated secret only when its file is absent and
preserves existing values.

On every converge the role stops, disables and removes the retired
`openhands-agent-server` and `openhands-automation` units, the shared
environment file from earlier revisions, and the `session-api-key` and
`automation-local-api-key` secret files.

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
