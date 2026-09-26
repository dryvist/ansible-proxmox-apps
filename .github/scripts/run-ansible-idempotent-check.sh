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
# Colored recap lines wrap "localhost" in an ANSI reset sequence before the
# whitespace run the grep below expects, so localhost[[:space:]]*: never
# matches and this falsely reports "not idempotent" on an actually-clean
# second run — force color off for the captured invocation, regardless of
# what the caller set for the first pass' own (human-read, not parsed) log.
output="$(PY_COLORS=0 ANSIBLE_FORCE_COLOR=0 ansible-playbook "$playbook" -c local)"
echo "$output"
echo "$output" | grep -E 'localhost[[:space:]]*:.*changed=0' || {
  echo "::error::second run of $playbook was not idempotent (expected changed=0)"
  exit 1
}
