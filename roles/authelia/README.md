# authelia

Authelia SSO portal / Traefik forwardAuth provider — a criticality-1 core
service (auth plane, beside ingress/DNS). One passkey login at the portal
opens every Traefik route whose tofu ingress row carries `sso = true`; the
`remember_me` session means roughly one login per week per browser.

## How it fits

- **Gate**: the `traefik` role renders an `authelia` forwardAuth middleware
  and attaches it to every ingress route with `sso: true` (the flag is set in
  tofu-proxmox `ingress.tf` and published through the inventory). Machine/API
  endpoints and apps with native client auth opt out there.
- **Login**: passkey-first (`webauthn.enable_passkey_login`) — Touch ID on the
  registering Mac, synced to other devices via the platform keychain. The
  bootstrap password exists only to create the account and register the first
  passkey.
- **State**: local SQLite on the persistent `/var/lib/authelia` mount
  (passkey registrations survive rebuilds). Sessions are in-memory: a service
  restart just re-prompts the browser.
- **Mail**: identity-verification mails go to the internal SMTP relay
  (Mailpit) — open its UI to click verification links.

## Secrets (Doppler / SOPS, env-injected)

| Env var | Purpose |
| --- | --- |
| `AUTHELIA_JWT_SECRET` | Identity-validation JWT signing secret |
| `AUTHELIA_SESSION_SECRET` | Session cookie encryption |
| `AUTHELIA_STORAGE_ENCRYPTION_KEY` | SQLite at-rest encryption (immutable once set) |
| `AUTHELIA_ADMIN_PASSWORD` | Bootstrap password for the admin user (first login + passkey registration) |

Generate each independently (64 random chars). The storage encryption key
cannot be changed after first start without resetting the database.

## Password rotation

`users.yml` is seeded once (create-if-absent — the salted hash would differ
every render). To rotate: update the Doppler secret, delete
`/etc/authelia/users.yml` on the guest via a converge with the file absent,
and re-run the role.

## First-time setup

1. Converge (`--tags authelia` + `traefik`, with `localhost` in `--limit`).
2. Browse to the portal, log in with the bootstrap password.
3. Settings → Security → register a WebAuthn credential (Touch ID).
4. Subsequent logins: passkey only, "Remember me" checked.
