#!/usr/bin/env bash
# Automated ingress-failover drill (NOT a manual runbook).
#
# Proves the keepalived VRRP virtual IP actually fails over: it finds the node
# currently holding the VIP, stops Traefik there, and asserts that (a) the VIP
# migrates to the surviving ingress node and (b) an HTTPS probe through the VIP
# still answers. Then it restores Traefik and re-asserts the VIP is back to a
# healthy 2-node state. Everything is derived from the tofu inventory — no
# hardcoded IPs. Safe by construction: an EXIT trap always restarts Traefik on
# every ingress node, so a failed assertion never leaves the proxy down.
#
# Intended to run in CI (or by an operator) where a LIVE ingress pair exists;
# it cannot run headless without one, which is exactly why it is a script and
# not a documented "click here to test failover" step.
#
# Usage:
#   ./scripts/ingress-failover-drill.sh [--probe-host NAME.SUBDOMAIN]
# Env:
#   INVENTORY_FILE   tofu inventory (default inventory/tofu_inventory.json)
#   SSH_USER         user for ssh to the ingress nodes (default root)
#   PROBE_PATH       HTTPS path to probe through the VIP (default /)
set -euo pipefail

INVENTORY_FILE="${INVENTORY_FILE:-inventory/tofu_inventory.json}"
SSH_USER="${SSH_USER:-root}"
PROBE_PATH="${PROBE_PATH:-/}"
SSH_OPTS=(-o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -o BatchMode=yes)

log()  { printf '\033[0;36m[drill]\033[0m %s\n' "$*"; }
ok()   { printf '\033[0;32m[ pass]\033[0m %s\n' "$*"; }
die()  { printf '\033[0;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

command -v jq >/dev/null || die "jq is required"
[[ -f "$INVENTORY_FILE" ]] || die "inventory not found: $INVENTORY_FILE"

VIP="$(jq -r '.ingress_vip // empty' "$INVENTORY_FILE")"
mapfile -t HOSTS < <(jq -r '.ingress_hosts[]? // empty' "$INVENTORY_FILE")

[[ -n "$VIP" ]] || die "inventory has no ingress_vip — ingress HA not deployed"
(( ${#HOSTS[@]} >= 2 )) || die "need >= 2 ingress_hosts for a failover drill, have ${#HOSTS[@]}"

log "VIP=$VIP  ingress nodes=${HOSTS[*]}"

on() { ssh "${SSH_OPTS[@]}" "${SSH_USER}@${1}" "${@:2}"; }

# Which node currently holds the VIP?
holder=""
for h in "${HOSTS[@]}"; do
  if on "$h" "ip -4 addr show | grep -qw '$VIP'"; then holder="$h"; break; fi
done
[[ -n "$holder" ]] || die "no ingress node currently holds $VIP — keepalived not converged"
log "current VIP holder: $holder"

# Always restore Traefik everywhere on exit, regardless of outcome.
restore() {
  log "restoring Traefik on all ingress nodes"
  for h in "${HOSTS[@]}"; do on "$h" "systemctl start traefik" || true; done
}
trap restore EXIT

# --- Induce failure on the holder ------------------------------------------
log "stopping Traefik on $holder to force VRRP failover"
on "$holder" "systemctl stop traefik"

# --- Assert the VIP migrated to a surviving node ---------------------------
new_holder=""
for _ in $(seq 1 15); do
  for h in "${HOSTS[@]}"; do
    [[ "$h" == "$holder" ]] && continue
    if on "$h" "ip -4 addr show | grep -qw '$VIP'"; then new_holder="$h"; break 2; fi
  done
  sleep 1
done
[[ -n "$new_holder" ]] || die "VIP $VIP did not migrate off $holder within 15s"
ok "VIP migrated $holder -> $new_holder"

# --- Assert HTTPS through the VIP still answers ----------------------------
probe_target="${1:-}"
if [[ "$probe_target" == "--probe-host" ]]; then probe_host="$2"; else probe_host="${PROBE_HOST:-}"; fi
if [[ -n "${probe_host:-}" ]]; then
  # Resolve the service name to the VIP so we exercise real SNI + routing.
  if curl -fsS -o /dev/null --resolve "${probe_host}:443:${VIP}" "https://${probe_host}${PROBE_PATH}"; then
    ok "HTTPS via VIP answered for ${probe_host}"
  else
    die "HTTPS via VIP failed for ${probe_host} after failover"
  fi
else
  # No service name given: confirm the VIP terminates TLS + answers HTTP from the
  # surviving node (no -f: a Traefik 404 on / is still a served response).
  if on "$new_holder" "curl -sS -o /dev/null -k https://${VIP}/"; then
    ok "VIP $VIP accepts HTTPS connections on the surviving node"
  else
    die "VIP $VIP not serving HTTPS after failover"
  fi
fi

# --- Restore + re-assert healthy 2-node state ------------------------------
log "restoring Traefik on $holder"
on "$holder" "systemctl start traefik"
trap - EXIT

sleep 3
back=""
for h in "${HOSTS[@]}"; do
  if on "$h" "ip -4 addr show | grep -qw '$VIP'"; then back="$h"; break; fi
done
[[ -n "$back" ]] || die "after restore, no node holds $VIP"
ok "ingress healthy again (VIP on $back)"
log "DRILL PASSED"
