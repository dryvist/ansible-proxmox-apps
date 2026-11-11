#!/usr/bin/env bash
# Publish one provider's token-quota windows as node_exporter textfile metrics.
#
# Configuration arrives only through the environment, set by the systemd unit:
#   QUOTA_EXECUTOR  executor label, for example zcode
#   QUOTA_URL       quota endpoint, read with GET
#   QUOTA_KEY_VAR   name of the environment variable that holds the API key
#   QUOTA_WINDOWS   comma-separated unit:window:seconds entries
#   QUOTA_OUTPUT    .prom file, replaced on success and removed on any failure
#
# The key is read from the environment and handed to curl through a file
# descriptor, so it never appears in an argument list, a log line or the journal.
set -euo pipefail

http_status=000
code=-
limit_keys=-
tmp=''

# Runs on every exit. It prints the single journal line, deletes the staging
# file, and removes the metrics file on any failure so no stale value remains.
finish() {
  local rc=$?
  printf 'http_status=%s code=%s limit_keys=%s\n' "$http_status" "$code" "$limit_keys"
  if [[ -n "$tmp" ]]; then
    rm -f -- "$tmp"
  fi
  if (( rc != 0 )) && [[ -n "${QUOTA_OUTPUT:-}" ]]; then
    rm -f -- "$QUOTA_OUTPUT"
  fi
  exit "$rc"
}
trap finish EXIT

main() {
  : "${QUOTA_EXECUTOR:?}" "${QUOTA_URL:?}" "${QUOTA_KEY_VAR:?}" "${QUOTA_WINDOWS:?}" "${QUOTA_OUTPUT:?}"
  local filter response body key now dir

  filter="$(dirname -- "${BASH_SOURCE[0]}")/agent-quota-probe.jq"
  key=${!QUOTA_KEY_VAR:-}
  [[ -n "$key" ]] || return 1

  response=$(curl --silent --proto '=https' --max-time 20 --write-out '\n%{http_code}' \
    --header @<(printf 'Authorization: %s\n' "$key") "$QUOTA_URL") || true
  unset key
  http_status=${response##*$'\n'}
  body=${response%$'\n'*}

  code=$(jq -r '.code // "-"' <<<"$body" 2>/dev/null) || true
  code=${code:--}
  limit_keys=$(jq -r 'try (.data.limits[0] | keys | join(",")) catch "-"' <<<"$body" 2>/dev/null) || true
  limit_keys=${limit_keys:--}

  [[ "$http_status" == 200 ]] || return 1

  now=$(date +%s)
  dir=$(dirname -- "$QUOTA_OUTPUT")
  tmp=$(mktemp -- "$dir/.agent-quota.XXXXXX")
  jq -r -f "$filter" --arg spec "$QUOTA_WINDOWS" --arg executor "$QUOTA_EXECUTOR" \
    --argjson now "$now" <<<"$body" >"$tmp"
  chmod 0644 -- "$tmp"
  mv -f -- "$tmp" "$QUOTA_OUTPUT"
  tmp=''
}

main "$@"
