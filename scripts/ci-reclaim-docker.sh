#!/usr/bin/env bash
# Reclaim shared Docker space before a Molecule scenario runs.
#
# Every scenario on a fleet runner pulls and builds on ONE shared dockerd. The
# runner role's own reclaim is a daily timer with a 24h age filter, which cannot
# help here: the full scenario matrix runs at the promotion gate and finishes in
# minutes, so a daily timer never comes between the jobs competing for the disk,
# and the age filter excludes exactly the images the burst just created. Reclaim
# therefore runs from the job, where the contention is.
#
# Deliberately NOT `docker system prune --all`: an image a sibling job is
# RUNNING is never a prune candidate, but one it has pulled and not yet started
# is, and evicting that only forces another job to re-pull. Stopped containers,
# dangling layers and build cache are the unbounded part and are safe to drop at
# any point.
#
# Never fails the caller. A reclaim that could not run is not a test result, and
# turning it into one would mask the scenario's real outcome.
set -u

usage() {
  cat >&2 <<'USAGE'
usage: ci-reclaim-docker.sh
Reclaims stopped containers, dangling images and build cache on the shared
Docker daemon. Takes no arguments. Always exits 0.
USAGE
}

[[ ${1:-} == -h || ${1:-} == --help ]] && { usage; exit 0; }

report_space() {
  df -h /var/lib/docker 2>/dev/null || df -h /
}

if ! command -v docker >/dev/null 2>&1; then
  echo "ci-reclaim-docker: no docker on PATH; nothing to reclaim" >&2
  exit 0
fi

echo "--- disk before reclaim"
report_space

docker container prune --force || true
docker image prune --force || true
docker builder prune --force || true

# VOLUMES ARE THE ONE THAT MATTERS, and they are NOT covered by any of the three
# above -- `docker system prune` excludes them too unless asked. Measured on a
# runner that had filled its disk: images, containers and build cache together
# held under 10GB, while 109 orphaned volumes held 88.42GB. Every scenario leaves
# one behind, so this is the category that grows without bound.
#
# Safe by construction: a volume referenced by ANY container, running or stopped,
# is not a prune candidate. A sibling job's volume is attached to its container
# and survives; only volumes whose container is already gone are removed.
docker volume prune --force || true

echo "--- disk after reclaim"
report_space

exit 0
