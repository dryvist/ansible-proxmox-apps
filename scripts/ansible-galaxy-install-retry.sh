#!/usr/bin/env bash
# ansible-galaxy install -r requirements.yml, retried. Galaxy has been
# flaking with 504 Gateway Timeout and client read timeouts several times a
# night across CI jobs — a transient upstream issue, not a real dependency
# problem, and rerunning the whole job to get past it wastes a runner slot
# for 40+ minutes. Five call sites duplicated this command; fixed once here.
set -euo pipefail

export ANSIBLE_GALAXY_SERVER_TIMEOUT="${ANSIBLE_GALAXY_SERVER_TIMEOUT:-60}"

attempts=4
for ((i = 1; i <= attempts; i++)); do
  if ansible-galaxy install -r requirements.yml "$@"; then
    exit 0
  fi
  if ((i < attempts)); then
    echo "ansible-galaxy install failed (attempt $i/$attempts) — retrying in $((i * 15))s" >&2
    sleep $((i * 15))
  fi
done

echo "ansible-galaxy install failed after $attempts attempts" >&2
exit 1
