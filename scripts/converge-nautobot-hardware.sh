#!/usr/bin/env bash
# Converge the Nautobot hardware ingest, in the two-stage order the runbook
# requires (docs/nautobot/hardware-ingest.md).
#
#   stage 1 (default): place the seed bundle, run NO seed jobs.
#   stage 2 (--commit): normal converge, which runs the seed jobs and writes.
#
# Between them, launch "Seed Hardware Inventory" from the Nautobot UI with its
# dry-run box ticked and confirm the counts. A converge cannot dry-run that job
# for you: the seed runner enqueues plain Jobs without kwargs.
#
# BEFORE RUNNING EITHER STAGE, the operator must confirm no one else holds a
# maintenance window on the Nautobot guest. This script cannot check that and
# deliberately does not pretend to.
#
# Stage 2 also performs a Nautobot MINOR UPGRADE, because the role now pins a
# version newer than what is running. That runs database migrations. Take a
# backup first.
#
# Run this from a GUI Terminal.app session, not from an agent shell: ansible
# is not an Apple platform binary, so the macOS Local Network gate blocks it
# from reaching guests on this Mac's own subnet.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
# REPO is derived from this script's own location, so a copy dropped elsewhere
# would cd somewhere plausible and fail deep inside ansible. Check it here.
[ -f "$REPO/playbooks/site.yml" ] || {
  echo "REPO=$REPO is not an ansible-proxmox-apps checkout (no playbooks/site.yml)." >&2
  echo "Run this script from inside the repo, or set REPO explicitly." >&2
  exit 1
}
: "${INT_HOMELAB_HARDWARE:?set INT_HOMELAB_HARDWARE to the generated hardware/inventory.seed.yml}"
[ -f "$INT_HOMELAB_HARDWARE" ] || { echo "no such file: $INT_HOMELAB_HARDWARE" >&2; exit 1; }

COMMIT=false
[ "${1:-}" = "--commit" ] && COMMIT=true

# --limit MUST include localhost: inventory/load_tofu.yml runs on localhost and
# populates the dynamic inventory via add_host. Without it every play reports
# "no hosts matched" and the run exits 0 having done nothing.
LIMIT="nautobot_group,localhost"

ARGS=(-i inventory/hosts.yml playbooks/site.yml --tags nautobot --limit "$LIMIT" --forks 5)
if [ "$COMMIT" = false ]; then
  # Place the bundle, run nothing. build_seed and run_seed_jobs are a pair by
  # design; this is the one sanctioned case for splitting them, and only in the
  # safe direction (assemble, do not execute).
  ARGS+=(-e nautobot_run_seed_jobs=false)
fi

echo "repo:     $REPO"
echo "slice:    $INT_HOMELAB_HARDWARE"
echo "stage:    $([ "$COMMIT" = true ] && echo 'COMMIT (writes to Nautobot)' || echo 'place bundle only')"
echo "command:  ansible-playbook ${ARGS[*]}"
echo

cd "$REPO"
exec doppler run -- ansible-playbook "${ARGS[@]}"
