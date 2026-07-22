---
name: openbao-plugins-first
description: OpenBao secrets engines are mandatory - never manual credential control
globs:
  - "roles/openbao/**"
  - "roles/openbao_secrets/**"
  - "playbooks/**openbao**"
---

# OpenBao: Plugins First, Always

## Principle

**If a resource has an OpenBao secrets engine, that engine is the only way its
credentials may be produced.** A credential a human minted, typed, pasted, or
stored in KV is *manual control*, and manual control is banned wherever an
engine exists.

**GitHub and AWS both have engines here, and both are enabled.** A static PAT
or a static AWS access key is therefore never the answer for either — not as a
default, not as a starting point, and not as a "temporary step until the engine
is wired up." The opt-in Slack POC uses OAuthapp at `oauthapp/`; its bot token
also belongs only in that engine, never in KV.

Upstream catalog: <https://github.com/openbao/openbao-plugins>

## Why

An engine-minted credential is short-lived, attributable to the run that asked
for it, revocable by lease, and impossible to leak durably. A static credential
is the opposite on all four counts: it lives until someone remembers to rotate
it, it is attributable only to whoever pasted it in, revoking it breaks every
unrelated consumer sharing it, and one transcript or log line leaks it forever.

The engines are already paid for — installed, version-pinned, checksum- and
signature-verified, and mounted. Reaching past a working engine for KV
re-introduces every property the engine was adopted to eliminate.

## What is live — check before you build

| Resource | Engine | Mount | Mint from |
| --- | --- | --- | --- |
| GitHub | `vault-plugin-secrets-github` | `github` | `github/token/<permission_set>` or the tiered AppRoles below |
| AWS | `openbao-plugins` secrets-aws | `aws` | `aws/sts/<role>` |
| Slack POC (opt-in) | `openbao-plugin-secrets-oauthapp` | `oauthapp` | `oauthapp/creds/slack-poc` |

Both default to enabled (`openbao_github_engine_enabled`,
`openbao_aws_engine_enabled` in `roles/openbao/defaults/main.yml`). AWS has been
converged and live for some time; the **GitHub engine was configured and
converged on 2026-07-17** (App `openbao-service-broker`, both installations,
read + per-repo-write + admin tiers). Engine-not-ready is never a licence to
seed a PAT: if the GitHub engine is ever found unconfigured on a cluster, the
fix is to converge it (supply the App credentials), not to reach for KV.

**GitHub — do not build a new grant.** Estate/AI identities that need a GitHub
token attach the `github-mint` base-capability policy
(`templates/github-mint-policy.hcl.j2`), which grants the **read-tier**
permission sets (`github/token/read-*`) only. The workstation git/gh path uses
the dedicated AppRoles instead: `github-read` (ambient all-repo read),
`github-write` (per-repo write via the parameter-pinned raw `github/token`
endpoint plus a claim lease), and the inert, human-gated `github-admin`. There
is no `secret/github/*` KV path and never was — do not add one, and do not
widen `github-mint` to reach the write or admin sets.

**AWS — same shape.** Consumers read `aws/sts/<role>` for short-lived STS
credentials. Never plumb `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

**Slack POC — OAuth V2 token rotation.** The engine holds the OAuth client and
refresh token after a one-time consent. The consumer AppRole can read only
`oauthapp/creds/slack-poc`; it cannot configure a server or write a credential.
Slack, not OpenBao, fixes the returned access-token lifetime at 12 hours, so an
OpenBao token's shorter TTL limits future reads but cannot invalidate a token
already returned to a caller.

## Rules

- **Never seed a credential into KV that an engine can mint.** `secret/github/*`
  holding PATs is the canonical violation. Reviewers reject it on sight.
- **Never add a KV-read policy for GitHub.** Attach `github-mint` instead.
- **A new resource gets a catalog check first.** Search
  [openbao/openbao-plugins](https://github.com/openbao/openbao-plugins) before
  designing anything. An engine that exists upstream but is not enabled here is
  a gap to close, not a licence to use KV.
- **KV is for values nothing can mint** — app config, third-party secrets with
  no engine, bootstrap material. That is its whole job.
- **The exception must be argued, with evidence.** If an engine genuinely cannot
  serve a purpose (a real GitHub App permission gap, say), the evidence is a
  cited API/docs limitation in the PR body. "The App probably can't do this" is
  not evidence, and an unevidenced assumption is not an exception.
- **A human-in-the-loop gate is not a reason to go static.** Gating *who may
  ask* is an auth/policy concern; it never changes *how the credential is
  produced*.

## Applying this

Before any OpenBao change, answer in the PR body:

1. Which resource's credentials does this touch?
2. Does an engine for it exist — enabled here, or upstream in `openbao-plugins`?
3. If yes: which mount path mints it, and which existing policy grants that?
4. If you are adding KV or a policy granting KV read for that resource: why can
   the engine not do this, with a citation?

Cannot answer 3 without inventing something new? You are almost certainly
duplicating a grant that already exists. Re-read
`roles/openbao/defaults/main.yml` — the base policies and capability leaves
cover more than they look like they do.
