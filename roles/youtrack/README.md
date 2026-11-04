# YouTrack Hub settings

This role preserves selected YouTrack Hub settings through the Hub REST API.
It runs from the Ansible controller and does not enter the YouTrack container.
Read requests run during check mode; writes are limited to detected drift and
check mode reports drift without sending writes.

The `Configure YouTrack Hub settings` play in
`playbooks/site/04-secrets-and-collab-apps.yml` runs on `localhost` with a local
connection. It is tagged `never` and `youtrack`, so it runs only with `--tags youtrack`
(its own Semaphore template), alongside the always-tagged
resource-domain pre-fetch in `playbooks/site/00-load-and-telemetry.yml`. That
pre-fetch calls the existing `dryvist.homelab.openbao_secrets` role, which
stores `openbao_secrets_by_domain` on `hostvars['localhost']`; the play reads
the `apps` domain there to supply `youtrack_hub_admin_token`. When `--tags youtrack`
selects this play, the pre-fetch includes localhost if no managed-secrets host
is in scope and fetches the apps domain even without a YouTrack inventory group.

Run the focused play from the repository's Ansible dev shell with:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags youtrack
```

## Managed settings

- Confirms the Hub setup is complete by authenticating as the token owner.
- Updates the existing Authelia OAuth 2.0 auth module's scope, provider URLs,
  client ID, user ID and full-name paths, user-creation setting, and enabled
  state. The desired scope is `openid profile email`; it does not include
  `groups`.
- Adds the configured Authelia identity link to existing Hub users when absent.

The Hub owner account and the OAuth module's client secret are created and
maintained outside this role. The module must already exist; the role does not
create it or manage its client secret.

## Variables

| Variable | Default or source | Purpose |
| --- | --- | --- |
| `youtrack_hub_base_url` | `https://youtrack.$PROXMOX_SUBDOMAIN` | Hub URL |
| `youtrack_hub_provider_url` | `https://authelia.$PROXMOX_SUBDOMAIN` | OIDC provider URL |
| `youtrack_hub_admin_token` | `bao_apps_secrets.youtrack_hub_admin_token` | Permanent Hub API token from apps-domain OpenBao |
| `youtrack_hub_auth_module_name` | `Authelia` | Existing Hub auth module to manage |
| `youtrack_hub_auth_module_fields` | See `defaults/main.yml` | Desired managed module fields |
| `youtrack_hub_identity_links` | `DEFAULT_USERNAME` for both login and identifier | Hub logins and matching provider usernames to link |

An empty `DEFAULT_USERNAME` skips the default identity link. Supply an explicit
`youtrack_hub_identity_links` list to manage other Hub users.
