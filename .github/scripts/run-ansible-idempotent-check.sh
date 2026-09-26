#!/usr/bin/env bash
# Runs an ansible-playbook fixture twice against the same fixed target
# directory (baked into the playbook itself) and fails unless the second run
# reports changed=0 — proves a checksum-marker-gated render is idempotent
# the way an operator re-running the role would exercise it, not merely that
# it runs once without error.
set -euo pipefail

playbook="$1"

echo "=== first pass: $playbook ==="
ansible-playbook "$playbook" -c local

echo "=== second pass: $playbook (must report changed=0) ==="
output="$(ansible-playbook "$playbook" -c local)"
echo "$output"
echo "$output" | grep -E 'localhost[[:space:]]*:.*changed=0' || {
  echo "::error::second run of $playbook was not idempotent (expected changed=0)"
  exit 1
}
