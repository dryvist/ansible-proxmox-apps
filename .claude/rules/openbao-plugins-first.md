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
is wired up."

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

## What is already enabled — check before you build

| Resource | Engine | Mount | Mint from |
| --- | --- | --- | --- |
| GitHub | `vault-plugin-secrets-github` | `github` | `github/token/<permission_set>` |
| AWS | `openbao-plugins` secrets-aws | `aws` | `aws/sts/<role>` |

Both default to enabled (`openbao_github_engine_enabled`,
`openbao_aws_engine_enabled` in `roles/openbao/defaults/main.yml`).

**GitHub — do not build a new grant.** The `github-mint` base-capability policy
(`templates/github-mint-policy.hcl.j2`) already grants
`github/token/<permission_set>` for every administrator-defined permission set,
and already composes with the KV leaves. An identity that needs a GitHub token
attaches `github-mint`. It does not get a new policy template, and it does not
get a KV path.

**AWS — same shape.** Consumers read `aws/sts/<role>` for short-lived STS
credentials. Never plumb `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

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
