# agent_guest

Converges a pooled Debian LXC into an autonomous AI agent guest: it pulls tasks
off a queue, runs one headless CLI agent per task, and opens a PR.

The **guest is the isolation boundary** — the same role the container plays in
[`agent_sandbox`](../agent_sandbox/README.md). These guests are disposable and
rebuilt from IaC; nothing irreplaceable lives on one.

## What it deploys

| Piece | Detail |
| --- | --- |
| `agent` user | uid 1000, home `/home/agent`, **no sudo**. Home is 0755 so the Cribl user can tail transcripts. |
| CLI toolchain | `claude`, `codex`, `gemini` (npm, unpinned), plus `git`, `gh`, `jq`, `ripgrep`, `gitleaks`, `awscli`, and the `bao` client. |
| Autonomous config | `.claude/settings.json`, `.codex/config.toml`, `.codex/rules/default.rules`, `.gemini/settings.json`, `.gemini/policies/autonomous.toml` |
| Task runner | `agent-task@<id>.service` (one instance per task) + `agent-queue.timer` poller |
| Secrets | OpenBao Agent in process-supervisor mode; no credential ever lands on disk |
| Log shipping | standalone Cribl Edge tailing the transcript trees |
| Secret gate | gitleaks pre-push hook via the agent user's global `core.hooksPath` |

## Installation

Included via the `Deploy autonomous agent guests` play in `playbooks/site.yml`
(hosts: `ai_agent_pool_group` — the pooled `ai-runner-pool-NN` LXCs, selected by
the `ai-proxied` profile tag in the tofu inventory). The three legacy
`ai-runner` guests are deliberately excluded: they are converged by the
`ai_runner` role in the peer `ansible-proxmox-ai` repo, and two roles must never
converge one guest.
Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags agent_guest,localhost --diff
```

## Usage

Submit a task by writing its object into the queue prefix; the poller picks it up
within `agent_guest_queue_poll_interval` and the guest opens the PR:

```sh
jq -n '{id: $id, repo: "dryvist/some-repo", cli: "codex", prompt: "task prompt"}' \
  --arg id "$(uuidgen)" |
  aws s3 cp - "$AGENT_QUEUE_URL/queue/$(uuidgen).json"
```

Watch a run, or start one by hand for a task already in the queue:

```sh
systemctl start agent-task@<task-id>.service
journalctl -fu agent-task@<task-id>.service
```

## Autonomous config mirror

`agent_guest_residual_deny` is a committed mirror of
[`dryvist/nix-ai`](https://github.com/dryvist/nix-ai)
`profiles.autonomous.residualDeny` — that repo is the source of truth.
Regenerate after upstream changes:

```sh
nix eval github:dryvist/nix-ai#lib.profiles.autonomous.residualDeny --json
```

The mirror is the **one source list**, not nix-ai's five rendered files: the
role's templates reproduce each tool's native format from it (Claude
`Bash(<prefix> *)` deny entries, Codex `prefix_rule` tokens, Gemini
Policy-Engine `commandPrefix` rules), which is exactly what
`nix eval github:dryvist/nix-ai#lib.renderAutonomous` does. Verified equal to
that render's output at the time of writing; the molecule verify asserts every
list entry reaches all three tools.

`.claude.json` is deliberately **not** deployed — it is Claude Code's mutable
runtime state, not part of the autonomous render.

## Task queue contract (v0)

`agent_guest_queue_url` is an S3/RustFS bucket URI. Layout:

```text
queue/<id>.json    task object, written by the submitter
leases/<id>        claim marker, written by exactly one worker
done/<id>.json     the task object, moved here after a terminal outcome
```

Task object: `{"id", "repo", "cli", "prompt", "base"}` where `cli` is
`claude|codex|gemini` and `base` defaults to `agent_guest_task_default_base`.

- **List** — the poller runs `aws s3 ls <queue>/queue/` and starts one
  `agent-task@<id>` per entry.
- **Claim** — the runner does a conditional `PutObject` of `leases/<id>` with
  `If-None-Match: *`. The store rejects the second writer with 412, so the claim
  is atomic with no lock service in the loop and no copy+delete race. A
  double-start is therefore harmless: the loser exits 0.

If RustFS ever refuses conditional PUT, move the claim to `flow-lock run` (the
estate's existing single-writer lease) rather than adding a retry heuristic.

With `agent_guest_queue_url` unset the timer stays disabled and the poller
no-ops — the role converges cleanly on a guest with no queue yet.

## OpenBao Agent wiring

`agent-task@.service` never runs the task script directly. `ExecStart` is
`bao agent -config=/etc/agent-guest/openbao-agent.hcl`, which:

1. authenticates with this guest's AppRole
   (`/etc/agent-guest/approle/{role_id,secret_id}`),
2. renders `GITHUB_TOKEN` from the **github secrets engine**
   (`agent_guest_github_token_path`) into the child environment — never to a
   sink, never to disk,
3. `exec`s the task runner as its supervised child.

The task id is not baked into the HCL: the unit passes `AGENT_TASK_ID=%i` and
the agent hands its environment to the child, so one config serves every
instance.

The AppRole credentials are **seeded out of band** (0640 `root:agent`); this role
creates the directory and never writes a secret into it. `bao agent` runs as the
`agent` user, so the guest's OpenBao identity is the agent user's — that is the
model, not an oversight. Scope the AppRole accordingly.

## Transcript shipping

A standalone Cribl Edge tails `/home/agent` for the three CLIs' transcript files
and ships them by `tcpjson` to the HAProxy-fronted Cribl Stream per-CLI
frontends. Ports come from the tofu `ai_log_routing` constant
(`claude_code` / `codex_cli` / `agy_cli`) — never a literal. A 4 MiB newline
breaker handles the oversized transcript lines.

The journal is **not** an input here: `roles/syslog_forwarder` already ships this
guest's journal (index=os), and the `agent-task` units log there like everything
else. If agent-unit logs need their own index, add an `agent_guest` entry to
`ai_log_routing` upstream rather than inventing a port here.

## Guest rebuild / pool return ordering

Implemented in `tasks/pool_return.yml`, tagged `never` so it only ever runs when
asked for explicitly:

```sh
ansible-playbook playbooks/site.yml --tags agent_guest_pool_return --limit <guest>,localhost
```

The order is load-bearing: (1) wait for the Cribl Edge persistent queue
(`/opt/cribl/state/queues`) to drain to zero files — a clean `systemctl stop` is
NOT delivery proof, the queue survives restarts by design, and the wait fails
loud after ~5 minutes rather than recycling a guest with an undeliverable
backlog; (2) stop Edge; (3) remove credentials; (4) wipe the workspace.
Reversed order strands undeliverable telemetry.

Codex (`~/.codex/auth.json`) and Gemini (`~/.gemini/oauth_creds.json`) auth
files are seeded out of band beside the AppRole credentials — they
self-refresh in place and `bao agent` env_template cannot render files.
