# zammad role

Installs Zammad (native packager.io DEB, colocated Elasticsearch and Redis) and
seeds its content — groups, service users and tokens, overviews, ticket
templates, jobs, SLAs, knowledge base — idempotently through the rails-runner
bootstrap under `files/zammad_bootstrap/`. All seed inputs arrive on the guest
as environment variables, never on a command line or in a staged data file.

## Outbound webhooks and triggers (off by default)

`zammad_webhooks` and `zammad_triggers` seed Zammad's native Webhook and
Trigger objects, so a new ticket can notify an external automation endpoint
that triages it. Both default to empty lists: with nothing declared the role
seeds nothing, changes no rendered input, and never touches or deletes objects
Zammad already has.

Seeding is idempotent by `name`: an entry is created when absent and updated
only in the fields that differ from its declaration. Fields an entry does not
declare are left untouched. A trigger's `webhook` is the name of a
`zammad_webhooks` entry — the seed resolves it to the Zammad id and builds the
trigger's action itself, so a trigger seeded here can only ever carry the
webhook action. `condition` is the product's own condition hash, passed
through unchanged.

Entries are validated before anything is written: names must be unique, the
endpoint must start with `https://`, a trigger must name a declared webhook,
and a `custom_payload` must be valid JSON once the product's `#{...}` ticket
placeholders are replaced. Before a custom payload or bearer token is used,
the seed checks that the installed Zammad's Webhook model actually has those
attributes and fails naming the missing one if not.

Example: post every new ticket in one group (Zammad group id `1`) to an
automation endpoint, with the endpoint's bearer token read from the
environment and a custom payload carrying ticket id, number, title, group and
priority:

```yaml
zammad_webhooks:
  - name: ticket-created
    endpoint: https://automation.example.com/hooks/ticket-created
    bearer_token: "{{ lookup('env', 'AUTOMATION_TICKET_HOOK_TOKEN') }}"
    custom_payload: |
      {
        "ticket_id": "#{ticket.id}",
        "ticket_number": "#{ticket.number}",
        "title": "#{ticket.title}",
        "group": "#{ticket.group.name}",
        "priority": "#{ticket.priority.name}"
      }

zammad_triggers:
  - name: notify-automation-ticket-created
    condition:
      ticket.action:
        operator: is
        value: [create]
      ticket.group_id:
        operator: is
        value: [1]
    webhook: ticket-created
```

Webhook entry fields: `name` (required), `endpoint` (required, `https://`),
`bearer_token` (optional — always from a lookup, never inline),
`ssl_verify` and `active` (default `true`), `custom_payload` (optional), and
`note`. Trigger entry fields: `name` (required), `condition` (required),
`webhook` (required), `activator` (default `action`),
`execution_condition_mode` (default `selective`), `active` (default `true`),
and `note`.

The bootstrap staging sweeps fragments the role no longer ships off the guest
before it runs, so a renamed or reverted seed file cannot keep executing.
