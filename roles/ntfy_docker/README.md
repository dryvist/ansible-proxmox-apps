# ntfy Docker role

## Zammad alert subscriber

The subscriber uses a stable key derived from topic and title. It records the first
firing as the ticket's opening article, suppresses unchanged firing repeats
until the configured interval, and includes the suppressed count and start time
in the next article. Tag or priority changes append immediately. A resolved
message appends its article and closes a ticket only when the bridge's
ntfy-zammad-managed tag is present and the ticket number is not denied.

Repeat state is written atomically to ntfy_docker_zammad_state_dir, the
persistent host directory already used by the subscriber spool. It survives
subscriber restarts. The bridge relies on the managed tag rather than reading
ticket articles, which avoids loading large incident histories.

Role variables:

- ntfy_docker_zammad_repeat_interval_seconds: unchanged firing interval in
  seconds before another article is appended; default 3600. Set to 0 to append
  every firing.
- ntfy_docker_zammad_close_denylist: ticket numbers the bridge never closes;
  default ['1000854'].
- ntfy_docker_zammad_state_dir: persistent directory for spool and repeat
  state; default /var/lib/ntfy-zammad.
