#!/usr/bin/env bash
# Reads the read-only Nautobot inventory credential from OpenBao at run time
# (secret/apps/nautobot: inventory_url + inventory_ro_token, published by
# roles/nautobot/tasks/readonly_token.yml) instead of carrying it in the run
# environment, then execs nautobot_drift.py with it as NAUTOBOT_URL/NAUTOBOT_TOKEN.
#
# AppRole login follows scripts/run-ansible.sh's identity order, but this
# template never runs that script, so it selects for itself: CONVERGE_ROLE_ID/
# SECRET_ID when a runner already chose, else the execution plane's own pair
# (the only pair the plane's run environment carries), else the shared
# OPENBAO_APPROLE_ANSIBLE_* pair for a workstation caller. secret_id is read
# from stdin, never passed as an argument -- every process on the host can
# read another's argv.
set -euo pipefail

: "${BAO_ADDR:?BAO_ADDR must be set}"
ROLE_ID=${CONVERGE_ROLE_ID:-${OPENBAO_APPROLE_SEMAPHORE_ROLE_ID:-${OPENBAO_APPROLE_ANSIBLE_ROLE_ID:-}}}
SECRET_ID=${CONVERGE_SECRET_ID:-${OPENBAO_APPROLE_SEMAPHORE_SECRET_ID:-${OPENBAO_APPROLE_ANSIBLE_SECRET_ID:-}}}
: "${ROLE_ID:?no AppRole in this environment (CONVERGE_ROLE_ID, OPENBAO_APPROLE_SEMAPHORE_ROLE_ID or OPENBAO_APPROLE_ANSIBLE_ROLE_ID)}"
: "${SECRET_ID:?no AppRole secret in this environment (CONVERGE_SECRET_ID, OPENBAO_APPROLE_SEMAPHORE_SECRET_ID or OPENBAO_APPROLE_ANSIBLE_SECRET_ID)}"

RUNNER_BAO_TOKEN=$(printf '%s' "$SECRET_ID" \
  | BAO_CLIENT_TIMEOUT=10 bao write -field=token auth/approle/login \
    role_id="$ROLE_ID" secret_id=-)
trap 'BAO_TOKEN=$RUNNER_BAO_TOKEN BAO_CLIENT_TIMEOUT=10 bao token revoke -self >/dev/null 2>&1 || true' EXIT

NAUTOBOT_URL=$(BAO_TOKEN=$RUNNER_BAO_TOKEN BAO_CLIENT_TIMEOUT=10 \
  bao kv get -mount=secret -field=inventory_url apps/nautobot)
NAUTOBOT_TOKEN=$(BAO_TOKEN=$RUNNER_BAO_TOKEN BAO_CLIENT_TIMEOUT=10 \
  bao kv get -mount=secret -field=inventory_ro_token apps/nautobot)
export NAUTOBOT_URL NAUTOBOT_TOKEN

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# Not `exec`: the EXIT trap above must still run afterwards to revoke the
# runner-owned token, and `exec` replaces this process before trap can fire.
python3 "$SCRIPT_DIR/nautobot_drift.py" "$@"
