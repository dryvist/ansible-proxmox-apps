# Secrets Management

**Runtime injection**: Doppler (`doppler run --`)
**At-rest encryption**: SOPS + age (`secrets.enc.yaml`)

See the [SOPS integration rule](agentsmd/rules/infra/sops-integration.md)
in ai-assistant-instructions for full patterns.

Template: `secrets.enc.yaml.example` — copy, fill in real values, then encrypt.

**Roles are injection-agnostic.** Every role reads a secret as plain
`lookup('env', 'KEY')` and doesn't know or care where the value came from —
never bake a specific backend (OpenBao, Doppler, SOPS) into a role default.
The secrets architecture (which store holds what, per-domain RBAC, the
workstation consumption path) is documented on the docs site, not here.

## OpenBao: always use the plugin, never manual credential control

**Read [`.claude/rules/openbao-plugins-first.md`](../../.claude/rules/openbao-plugins-first.md)
before making any OpenBao change of any kind.** It is the binding rule, not a
suggestion, and it is short.

The one-line version: if a resource has an OpenBao **secrets engine**, that
engine is the only way its credentials may be produced. A credential a human
minted, typed, pasted, or stored in KV is manual control and is banned wherever
an engine exists. **GitHub and AWS both have engines here and both are live**
(AWS long-standing; GitHub configured + converged 2026-07-17) — so a static PAT
or a static AWS access key is never the answer, never a starting point, and
never a "temporary" step. Engine-not-ready is never a licence to seed a PAT.

| Resource | Engine (live) | Mint from | Never |
| --- | --- | --- | --- |
| GitHub | `vault-plugin-secrets-github` @ `github` | `github/token/<set>` — read / per-repo-write / admin tiers (see rule) | a PAT in `secret/github/*` |
| AWS | [`openbao-plugins`](https://github.com/openbao/openbao-plugins) secrets-aws @ `aws` | `aws/sts/<role>` | a static access key |

GitHub token tiers: estate/AI identities attach `github-mint` (read sets only);
the workstation git/gh path uses the `github-read` / `github-write` (per-repo,
lease-gated) / `github-admin` (human-gated) AppRoles. No `secret/github/*` path
exists — see the rule.

Adding a **new** resource? Check
[openbao/openbao-plugins](https://github.com/openbao/openbao-plugins) for an
engine first. An engine that exists upstream and is not enabled here is a gap to
close, not a reason to reach for KV.
