#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'usage: %s {router-down|judge-down|hermes-failure}\n' "$0" >&2
  exit 2
fi

case "$1" in
  router-down)
    alert_name='LLM router down'
    severity=critical
    ;;
  judge-down)
    alert_name='LLM judge down'
    severity=warning
    ;;
  hermes-failure)
    alert_name='Hermes LLM requests failing'
    severity=warning
    ;;
  *)
    printf 'unknown alert: %s\n' "$1" >&2
    exit 2
    ;;
esac

: "${GRAFANA_URL:?set GRAFANA_URL}"
: "${GRAFANA_API_TOKEN:?set GRAFANA_API_TOKEN}"
: "${GRAFANA_ALERT_CRIBL_HEC_URL:?set GRAFANA_ALERT_CRIBL_HEC_URL}"
: "${SPLUNK_HEC_TOKEN:?set SPLUNK_HEC_TOKEN}"

endpoint="${GRAFANA_URL%/}/api/alertmanager/grafana/config/api/v1/receivers/test"

jq -n \
  --arg alert_name "$alert_name" \
  --arg severity "$severity" \
  --arg url "$GRAFANA_ALERT_CRIBL_HEC_URL" \
  '{
    alert: {
      labels: {alertname: $alert_name, severity: $severity, test: "true"},
      annotations: {summary: ("Synthetic route test for " + $alert_name)}
    },
    receivers: [{
      name: "cribl-alerts",
      grafana_managed_receiver_configs: [{
        uid: "cribl-alerts",
        name: "cribl-alerts",
        type: "webhook",
        disableResolveMessage: false,
        settings: {
          url: $url,
          httpMethod: "POST",
          authorization_scheme: "Splunk"
        },
        secureSettings: {
          authorization_credentials: env.SPLUNK_HEC_TOKEN
        }
      }]
    }]
  }' |
  curl --config <(cat <<EOF
header = "Authorization: Bearer ${GRAFANA_API_TOKEN}"
EOF
  ) \
    --fail-with-body --silent --show-error \
    --request POST \
    --header 'Content-Type: application/json' \
    --data-binary @- \
    "$endpoint"
