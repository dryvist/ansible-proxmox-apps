#!/usr/bin/env bash
# Build the github_runner image and assert its pre-baked toolchain, so image
# defects surface at PR time instead of on the converged fleet.
set -euo pipefail

# Assemble the same build context the role assembles at converge time.
ctx=$(mktemp -d)
trap 'rm -rf "$ctx"' EXIT
cp roles/github_runner/files/Dockerfile roles/github_runner/files/entrypoint.sh "$ctx/"
cp requirements.yml "$ctx/"

docker build -t runner-image-smoke "$ctx"

docker run --rm --entrypoint "" runner-image-smoke sh -eu -c '
  python3 --version
  uv --version
  ansible --version
  ansible-galaxy --version
  molecule --version
  ansible-lint --version
  sops --version
  yq --version
  gh --version
  # Jobs run as the unprivileged runner user; anything needing root goes
  # through sudo. Dropping it from the image broke template-render CI.
  command -v sudo
  v=$(/home/runner/actions-runner/bin/Runner.Listener --version)
  echo "runner=$v"
  maj=${v%%.*}; rest=${v#*.}; min=${rest%%.*}
  # node24-based actions (checkout v7+) require runner >= 2.328
  if [ "$maj" -lt 2 ] || { [ "$maj" -eq 2 ] && [ "$min" -lt 328 ]; }; then
    echo "runner $v too old for node24 actions (need >= 2.328)" >&2
    exit 1
  fi
'
