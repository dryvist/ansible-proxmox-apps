#!/usr/bin/env bash
set -euo pipefail

export RUN_ANSIBLE_IDENTITIES="${RUN_ANSIBLE_IDENTITIES:-openbao-node-converge?,signer?,semaphore?,ansible-converge?,ansible?}"
export RUN_ANSIBLE_SIGN_ROLE_OPENBAO_NODE_CONVERGE="${RUN_ANSIBLE_SIGN_ROLE_OPENBAO_NODE_CONVERGE:-automation-ansible}"
export RUN_ANSIBLE_SIGN_ROLE_ANSIBLE_CONVERGE="${RUN_ANSIBLE_SIGN_ROLE_ANSIBLE_CONVERGE:-automation-ansible}"
export SSH_CERT_TTL="${SSH_CERT_TTL:-2h}"
export RUN_ANSIBLE_RETIRING_IDENTITIES="${RUN_ANSIBLE_RETIRING_IDENTITIES:-ansible}"
export RUN_ANSIBLE_WARN_NO_ISSUER="${RUN_ANSIBLE_WARN_NO_ISSUER:-1}"
export RUN_ANSIBLE_EXPORT_CONVERGE_IDENTITY="${RUN_ANSIBLE_EXPORT_CONVERGE_IDENTITY:-1}"
export RUN_ANSIBLE_PIN_FILE="${RUN_ANSIBLE_PIN_FILE:-servarr.pin}"
export RUN_ANSIBLE_PIN_DIR="${RUN_ANSIBLE_PIN_DIR:-servarr}"
export RUN_ANSIBLE_PIN_URL="${RUN_ANSIBLE_PIN_URL:-${MEDIA_STACK_REPO_URL:-}}"
export RUN_ANSIBLE_PIN_PLAYBOOKS="${RUN_ANSIBLE_PIN_PLAYBOOKS:-05-media-and-gate.yml,site/05-media-and-gate.yml,playbooks/site/05-media-and-gate.yml}"
export RUN_ANSIBLE_PIN_OPTIONAL_PLAYBOOKS="${RUN_ANSIBLE_PIN_OPTIONAL_PLAYBOOKS:-site.yml,playbooks/site.yml}"
export RUN_ANSIBLE_CHECKOUT_GUARD="${RUN_ANSIBLE_CHECKOUT_GUARD:-1}"
export RUN_ANSIBLE_MERGE_KNOWN_HOSTS="${RUN_ANSIBLE_MERGE_KNOWN_HOSTS:-1}"
export RUN_ANSIBLE_LIMIT_LOCALHOST="${RUN_ANSIBLE_LIMIT_LOCALHOST:-1}"
export RUN_ANSIBLE_RECAP_CHECK="${RUN_ANSIBLE_RECAP_CHECK:-1}"
export RUN_ANSIBLE_LOG_DIR="${RUN_ANSIBLE_LOG_DIR:-$(git rev-parse --show-toplevel)/.ansible-run-logs}"

# macOS: Objective-C fork safety and CFNetwork proxy lookup crash forked Ansible workers.
if [ "$(uname -s)" = Darwin ]; then
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
  export no_proxy="${no_proxy-*}"
  export NO_PROXY="${NO_PROXY-*}"
fi

# renovate: datasource=github-releases depName=dryvist/homelab-contracts
HOMELAB_CONTRACTS_REF=v5.58.1
exec nix run "github:dryvist/homelab-contracts/${HOMELAB_CONTRACTS_REF}#run-ansible" -- "$@"
