# Tool Execution — Nix Dev Shell

This repo provides all tools via a Nix dev shell (flake.nix + .envrc).

## Rules (local workstation / Nix dev shell)

- Run ansible, ansible-lint, molecule, and all Python tools as bare commands
- If a tool is not found on PATH, use `direnv exec . <command>` — do not install tools globally
- Do **not** use `pipx`, `pip install`, or `uv pip install` to install tools locally
- Do **not** prefix commands with `uv run` — tools are on PATH from the dev shell
- CI workflows and ephemeral containers may use `uv pip install --system` as configured in their workflows — these rules apply to local development only

## Why

pipx/uv venvs reference Nix store Python interpreters that get garbage-collected.
Any globally-installed Python tool WILL break after the next nix-collect-garbage.
