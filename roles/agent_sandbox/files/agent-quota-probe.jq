# Renders one token-quota response as node_exporter textfile lines.
# Inputs: $spec "unit:window:seconds,...", $executor, $now (epoch seconds).
# Any unexpected shape stops the program before it prints a line, so the
# caller writes no file and the previous metrics are removed.
def fail($reason): error($reason);
def is_number: type == "number";

(($spec | split(",")) | map(split(":") | {key: .[0], value: {window: .[1], seconds: (.[2] | tonumber)}}) | from_entries) as $windows
| if .code == 200 then . else fail("code") end
| if (.data.limits | type) == "array" and (.data.limits | length) > 0 then . else fail("limits") end
| [.data.limits[] | select(.type == "TOKENS_LIMIT")] as $tokens
| if ($tokens | length) > 0 then . else fail("no token windows") end
| if ($tokens | map(.unit | tostring) | unique | length) == ($tokens | length) then . else fail("duplicate unit") end
| ([$tokens[] | (.unit | tostring) as $unit
    | ($windows[$unit] // fail("unknown unit")) as $window
    | if (.percentage | is_number) and (.nextResetTime | is_number) then . else fail("missing field") end
    | (["executor=\"\($executor)\"", "window=\"\($window.window)\"", "source=\"provider_api\""] | join(",")) as $labels
    | "agent_quota_used_percent{\($labels)} \(.percentage)",
      "agent_quota_window_seconds{\($labels)} \($window.seconds)",
      "agent_quota_reset_timestamp_seconds{\($labels)} \(.nextResetTime / 1000)"
  ] + ["agent_quota_probe_last_success_timestamp_seconds{executor=\"\($executor)\"} \($now)"])
| .[]
