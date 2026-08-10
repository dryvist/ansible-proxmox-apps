#!/bin/bash
set -euo pipefail

# Register this container as one runner in the organization pool.
#
# Credential chain, all at start time and none of it written to disk:
#   AppRole role_id/secret_id -> OpenBao token -> GitHub App installation token
#   (organization_self_hosted_runners:write only) -> registration token.
#
# A registration token expires in an hour and these containers restart, so the
# ability to mint one has to be standing. It is an AppRole rather than a
# personal access token so it is revocable, audited, and cannot read a single
# line of source. There is deliberately no PAT fallback: a fallback that works
# is the credential everyone ends up on.

require() {
  local name=$1
  if [ -z "${!name:-}" ]; then
    echo "ERROR: $name is empty. The runner cannot register without it." >&2
    exit 1
  fi
}

require BAO_ADDR
require BAO_ROLE_ID
require BAO_SECRET_ID
require GITHUB_ORG
require RUNNER_GROUP

bao_login() {
  local body
  body=$(jq -nc --arg r "$BAO_ROLE_ID" --arg s "$BAO_SECRET_ID" \
    '{role_id:$r, secret_id:$s}')
  curl -sf -X POST --data "$body" "${BAO_ADDR}/v1/auth/approle/login" \
    | jq -re '.auth.client_token'
}

# The permission-set path ignores request bodies, so the minted token carries
# exactly the stored map and cannot be widened from here.
github_token() {
  local bao_token=$1
  curl -sf -H "X-Vault-Token: ${bao_token}" \
    "${BAO_ADDR}/v1/${BAO_GITHUB_MOUNT:-github}/token/${BAO_PERMISSION_SET}" \
    | jq -re '.data.token'
}

registration_token() {
  local gh_token=$1
  curl -sf -X POST \
    -H "Authorization: token ${gh_token}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/orgs/${GITHUB_ORG}/actions/runners/registration-token" \
    | jq -re '.token'
}

mint() {
  local bao_token gh_token
  bao_token=$(bao_login) || {
    echo "ERROR: OpenBao AppRole login failed at ${BAO_ADDR}. Check that the" \
      "github-runner role_id/secret_id are current." >&2
    return 1
  }
  gh_token=$(github_token "$bao_token") || {
    echo "ERROR: could not mint a GitHub token from permission set" \
      "${BAO_PERMISSION_SET}. Check that the github-runner policy grants it." >&2
    return 1
  }
  registration_token "$gh_token" || {
    echo "ERROR: GitHub refused a registration token for org ${GITHUB_ORG}." \
      "The App installation needs organization_self_hosted_runners:write." >&2
    return 1
  }
}

RUNNER_NAME="${RUNNER_NAME_PREFIX:-proxmox-runner}-${HOSTNAME}"

if [ ! -f .runner ]; then
  # --runnergroup places the runner in the restricted group. Without it the
  # runner lands in Default, which is visible org-wide — and these runners
  # bind-mount docker.sock, so that would hand root on this host to every
  # repository in the organization.
  ./config.sh \
    --url "https://github.com/${GITHUB_ORG}" \
    --token "$(mint)" \
    --runnergroup "${RUNNER_GROUP}" \
    --labels "${RUNNER_LABELS:-self-hosted,Linux}" \
    --name "${RUNNER_NAME}" \
    --unattended \
    --replace
fi

cleanup() {
  # Deregistration needs a fresh removal token, and the runner may have been up
  # for weeks — so mint one now rather than holding anything from startup. A
  # failure here leaves an offline runner in the group, which is untidy but
  # harmless; never block shutdown on it.
  local bao_token gh_token remove_token
  bao_token=$(bao_login 2>/dev/null) || return 0
  gh_token=$(github_token "$bao_token" 2>/dev/null) || return 0
  remove_token=$(curl -sf -X POST \
    -H "Authorization: token ${gh_token}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/orgs/${GITHUB_ORG}/actions/runners/remove-token" \
    2>/dev/null | jq -re '.token') || {
    echo "Warning: no removal token; remove ${RUNNER_NAME} from the group by hand."
    return 0
  }
  ./config.sh remove --token "$remove_token" 2>/dev/null || true
}
trap cleanup EXIT

exec ./run.sh
