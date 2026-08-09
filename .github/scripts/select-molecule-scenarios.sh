#!/usr/bin/env bash
# Emit the Molecule scenario matrix for the current PR to $GITHUB_OUTPUT.
#
# Thin wrapper: the selection policy lives in
# scripts/select_molecule_scenarios.py, which is unit-tested (--demo). This only
# works out what changed and hands it over.
set -euo pipefail

: "${BASE_REF:?BASE_REF must be set to the PR base branch}"
: "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"

git fetch -q --depth=1 origin "$BASE_REF"

# Three-dot: what this branch introduced, not everything that landed on the base
# since the branch was cut. Two-dot would widen the matrix on every unrelated
# merge to the base, which is the behaviour being removed.
changed="$(git diff --name-only "origin/${BASE_REF}...HEAD")"

echo "Changed paths:"
printf '%s\n' "$changed" | sed 's/^/  /'

scenarios="$(printf '%s\n' "$changed" | python3 scripts/select_molecule_scenarios.py)"
echo "Selected scenarios: ${scenarios}"

printf 'scenarios=%s\n' "$scenarios" >> "$GITHUB_OUTPUT"
if [ "$scenarios" = "[]" ]; then
  printf 'any=false\n' >> "$GITHUB_OUTPUT"
else
  printf 'any=true\n' >> "$GITHUB_OUTPUT"
fi
