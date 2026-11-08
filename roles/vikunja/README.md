# vikunja

Installs [Vikunja](https://vikunja.io), the task manager behind this
homelab's agent task queues, as a native Go binary on an LXC. The API and web
UI share one port; state lives in the shared native Postgres cluster.

## Outgoing requests

Webhooks may target private network addresses. This rests on two assumptions:
webhooks are created only through this repository's automation, and every
Vikunja user is the operator or an agent bot. If either assumption changes,
turn `vikunja_outgoing_requests_allow_non_routable_ips` off or route webhooks
through a proxy (`outgoingrequests.proxyurl`).
