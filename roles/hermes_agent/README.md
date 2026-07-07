# hermes_agent

Deploys the **[NousResearch Hermes Agent](https://github.com/nousresearch/hermes-agent)**
— the self-improving **autonomous agent** — headless in a dedicated LXC on the AI
VLAN.

> This is **not** the `ollama` / `open_webui` (`hermes-infer` / `hermes-chat`) LLM
> *serving* stack. Those serve the Hermes-4 *model*; this role runs the *agent*,
> which uses that model (or any OpenAI-compatible endpoint) as its brain.

## What it does

- Installs Hermes Agent system-wide via the official installer (bundles Python/uv +
  Node), once, behind a `creates` guard. The installer is fetched from the pinned
  release tag's raw URL and **sha256-verified before it runs** — never
  `curl <url> | bash` of a moving remote script — and `--branch <tag>` pins the
  app checkout to the same release. The Hermes daemon owns subsequent updates
  (`hermes update`) — Ansible owns only the platform, so converge stays idempotent.
- Runs the `hermes gateway` daemon under a dedicated non-root `hermes` user via
  systemd. The gateway drives the built-in **cron** scheduler and the **Kanban**
  dispatcher (autonomy) even with no messaging platform configured.
- `HERMES_HOME` (`/var/lib/hermes/.hermes`) lives on a dedicated ZFS data volume —
  memory, skills, profiles, the Kanban DB, sessions and logs — so it is snapshotted
  and replicated pve→pve3 (the agent's accumulated knowledge is irreplaceable).
- Points the model backend at the LiteLLM router (`hermes-4-14b` via
  `llm.<subdomain>/v1`, OpenAI-compatible); sets memory provider to **Hindsight** (best self-hostable
  June 2026) alongside the always-on `MEMORY.md`/`USER.md`; caps `agent.max_turns`
  so a runaway loop can't pin the GPU overnight.
- Wires the Slack gateway (Socket Mode) via five env vars in `.env`, read
  directly by Hermes' own Slack adapter — no `config.yaml` changes needed.
  All five default to empty, so the gateway simply runs Slack-free until they
  are set.
- Seeds a daily cron job that summarizes the homelab AI fabric status and posts
  it to the Slack home channel; activation happens on the next converge.

## Installation

This role ships in the `ansible-proxmox-apps` repository — no separate
installation. The role itself fetches and sha256-verifies the pinned Hermes
installer on the target, so the LXC only needs base connectivity and apt.

## Usage

Run the role against its inventory group:

```bash
doppler run -- uv run ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml \
  --tags hermes_agent
```

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `hermes_agent_home` | `/var/lib/hermes` | data-volume mount = the user home |
| `hermes_agent_model_base_url` | `https://llm.{{ PROXMOX_SUBDOMAIN }}/v1` (router) | the brain endpoint |
| `hermes_agent_model` | `hermes-4-14b` | model id |
| `hermes_agent_memory_provider` | `hindsight` | external memory provider |
| `hermes_agent_max_turns` | `90` | agentic-loop budget |
| `hermes_agent_slack_bot_token` | `""` | Slack bot OAuth token (`xoxb-…`) |
| `hermes_agent_slack_app_token` | `""` | Slack app-level token for Socket Mode (`xapp-…`) |
| `hermes_agent_slack_allowed_users` | `""` | comma-sep Slack member IDs allowed to DM the bot |
| `hermes_agent_slack_home_channel` | `""` | Slack channel ID for proactive posts |
| `hermes_agent_slack_home_channel_name` | `""` | Slack channel display name |

## Group / invocation

Targets `hermes_agent_group`, derived from the `hermes-agent` tag in `load_tofu.yml`.
Run via `site.yml` (`--tags hermes_agent`).

## Not yet live-validated

Verify on the first converge: (a) `install.sh` runs clean non-interactively as root
on a minimal Debian LXC; (b) `hermes gateway run --replace` stays up headless with no
messaging platform; (c) Hindsight initialises from `config.yaml` alone (it may need
its client package on first run — `memory status` check is non-fatal so it surfaces
without failing the converge). Single-profile first; profiles + Kanban teams + a
messaging gateway are a documented follow-up (the whole `HERMES_HOME` is already
persisted for them).

## LLM knowledge base (llm-wiki)

Enables the bundled `research/llm-wiki` skill so Hermes builds and maintains an
interlinked Markdown "second brain" from raw sources (build / query / lint /
maintain, with SHA256 source-drift detection). The wiki lives at `WIKI_PATH` =
`{{ hermes_agent_wiki_path }}` (`/var/lib/hermes/wiki`) — under the persistent
ZFS volume, so it is snapshotted and replicated. A nightly cron seeds a
lint/health-check. Context compression is enabled (`summary_model` pointed at the
router, since the upstream Google default is unreachable here) so long autonomous
sessions don't overflow.

| Variable | Default | Meaning |
| --- | --- | --- |
| `hermes_agent_wiki_enabled` | `true` | enable llm-wiki + create the wiki dir |
| `hermes_agent_wiki_path` | `{{ hermes_agent_home }}/wiki` | persistent wiki root (`WIKI_PATH`) |
| `hermes_agent_context_compression_enabled` | `true` | auto-shrink long sessions |
| `hermes_agent_context_compression_threshold` | `0.85` | compress at 85% of context |
| `hermes_agent_nightly_wiki_cron_*` | — | nightly lint/health-check cron |

## Autonomous GitHub docs-contributor

Gives Hermes a **read public dryvist repos + open signed, draft, no-merge doc PRs**
capability against `dryvist/docs` and `dryvist/docs-starlight`, via a dedicated
GitHub App (`hermes-docs-bot`). Commits are authored through the
`createCommitOnBranch` GraphQL mutation so GitHub marks them **Verified/signed**
(a plain `git push` is rejected by the org's required-signatures ruleset). The
bundled `dryvist/docs-pr` skill enforces the guardrails: draft-only, attribution
triad, dated branches, `docs:` Conventional-Commit titles, per-repo/day caps +
de-dup, secret redaction, and absolute privacy routing (sensitive → docs-starlight
only). **No-merge** is guaranteed by the org ruleset (human review + signatures,
the App is not a bypass actor), not by the token scope.

App creds are delivered from OpenBao `secret/ai/hermes` (`bao_local_llm_secrets`)
with an env fallback; the PEM is written to `{{ hermes_agent_hermes_home }}/github-app.pem`
(`0600`, `no_log`). The role stays inert until the creds are set.

| Variable | Default | Meaning |
| --- | --- | --- |
| `hermes_agent_github_app_id` | `""` | GitHub App ID (bao/env) |
| `hermes_agent_github_app_installation_id` | `""` | App installation ID (bao/env) |
| `hermes_agent_github_app_private_key` | `""` | App PEM (bao/env; written to a 0600 file) |

Helper unit tests: `roles/hermes_agent/files/skills/dryvist/docs-pr/tests/` — run
`python -m pytest` from that skill dir (all guardrail logic, no network).
