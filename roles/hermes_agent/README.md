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
  and replicated to the DR node (the agent's accumulated knowledge is irreplaceable).
- Points the model backend at the LiteLLM router (`Qwen3-Coder-30B-A3B` via
  `llm.<subdomain>/v1`, OpenAI-compatible, 262144 context); sets memory provider to **Hindsight** (best self-hostable
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
| `hermes_agent_model` | `Qwen3-Coder-30B-A3B` | model id (LiteLLM router alias) |
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

## GitHub issues & projects

Delivers a fine-grained PAT (`GH_PAT_WRITE_PROJECT_ISSUES`) into `.env` giving
Hermes **read/write Issues across all repos** and **read/write Projects (v2) in
the `dryvist` org** — for triaging, creating and updating issues and managing
project boards. It is deliberately least-privilege: **not** for code commits (that
is the signed `docs-pr` / GitHub App path) and **not** for merges. Bao-first
(`secret/ai/hermes`, `bao_local_llm_secrets`) with an env fallback; empty until the
token is set. The bundled `dryvist/github-issues` skill documents the REST (issues)
and GraphQL (Projects v2) calls and the usage guardrails.

| Variable | Default | Meaning |
| --- | --- | --- |
| `hermes_agent_github_issues_pat` | `""` | issues + org-projects PAT (bao/env) |

## Splunk search access

Registers the **Splunk MCP Server** (Splunkbase 7931, deployed by `ansible-splunk`)
as an HTTP MCP server in `~/.hermes/config.yaml` (`mcp_servers.splunk`), so Hermes
can query the environment — `run_splunk_query`, `get_indexes`, `get_sourcetypes` —
with its own scoped identity. The URL and Bearer token are referenced as
`${SPLUNK_MCP_URL}` / `${SPLUNK_MCP_TOKEN}` and resolved from `.env` at connect
time, so neither the endpoint nor the token ever lands in `config.yaml`.

Creds come from OpenBao `secret/ai/hermes` (`bao_local_llm_secrets`) with an env
fallback. `ansible-splunk` mints the per-user token (a Splunk token is bound to a
user and inherits its roles) and publishes it as `SPLUNK_MCP_TOKEN`. The
`mcp_servers.splunk` entry is omitted until the URL is set, so the agent starts
cleanly before the creds exist.

| Variable | Default | Meaning |
| --- | --- | --- |
| `hermes_agent_splunk_mcp_enabled` | `true` | Register the Splunk MCP server |
| `hermes_agent_splunk_mcp_url` | `""` | Splunk MCP Server endpoint (bao/env) |
| `hermes_agent_splunk_mcp_token` | `""` | Bearer token (bao/env) |

## Live docs (Context7)

Registers Context7's hosted HTTP MCP server (`mcp_servers.context7`) so Hermes
can pull **current, version-specific library/framework docs** on demand instead
of relying on stale training data. The API key is referenced as
`${CONTEXT7_API_KEY}` (resolved from `.env`), bao-first (`secret/ai/hermes`) with
env fallback; the entry is omitted until the key is set.

| Variable | Default | Meaning |
| --- | --- | --- |
| `hermes_agent_context7_mcp_enabled` | `true` | Register the Context7 MCP server |
| `hermes_agent_context7_api_key` | `""` | Context7 API key (bao/env) |

## Escalation (Codex via MCP)

Registers `codex mcp-server` (OpenAI's Codex CLI) as an MCP tool
(`mcp_servers.codex`) — a deliberate escalation path for problems worth a
stronger model, or a session that's stuck/looping. This is **not** automatic
on-error fallback (Hermes' own `fallback_providers` feature is intentionally
unused here); tool use is inherently a per-call, model-chosen decision, so
the agent reaches for Codex only when it judges the problem warrants it, the
same way it decides whether to call any other tool.

Codex runs under a completely separate, low-privilege OS user —
`codex-runner`, provisioned by the sibling `codex_runner` role on the same
host — never as `hermes`. The MCP entry invokes it through a single-command
`sudo` grant (`hermes` → `codex-runner`, exactly `codex mcp-server`, nothing
else); Hermes never gains filesystem access to that user's ChatGPT-OAuth
credential, so the token itself is not directly readable by the agent even
though the agent can fully use the tool.

Codex's OAuth login is a manual, one-time, interactive step that cannot be
automated by Ansible — see `roles/codex_runner/README.md` for both bootstrap
options (fresh `codex login`, or copying an already-authenticated
`~/.codex/auth.json`). Until that's done, the MCP entry is present but every
call to it errors; the daemon itself starts and runs normally regardless.

`OPENROUTER_API_KEY` is already seeded in OpenBao `secret/ai/hermes` (from an
earlier pass at this problem) but is **not consumed** by anything in this
role — parked for a possible future escalation option, not wired to an
active MCP/delegation target this round.

| Variable | Default | Meaning |
| --- | --- | --- |
| `hermes_agent_codex_mcp_enabled` | `true` | Register the Codex MCP server |
