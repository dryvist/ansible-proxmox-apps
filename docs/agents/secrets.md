# Secrets Management

**At-rest encryption**: SOPS + age (`secrets.enc.yaml`)

See the [SOPS integration rule](agentsmd/rules/infra/sops-integration.md)
in ai-assistant-instructions for full patterns.

Template: `secrets.enc.yaml.example` — copy, fill in real values, then encrypt.

**Roles are injection-agnostic.** Every role reads a secret as plain
`lookup('env', 'KEY')` and doesn't know or care where the value came from —
never bake a specific secrets backend into a role default.

## The `openbao` role

The `openbao` role lives in the `dryvist.secrets_management` collection, not in
this repository. Changes to it are made there and follow
[`.claude/rules/openbao-plugins-first.md`](../../.claude/rules/openbao-plugins-first.md).
