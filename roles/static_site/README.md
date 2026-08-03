# static_site

Serves a directory of static files over plain HTTP with nginx from the distro
repository, on a Debian/Ubuntu LXC.

TLS terminates upstream at the reverse proxy, so this role never touches
certificates, ACME, or port 443. It installs nginx, writes one vhost, and
mirrors a document root from a control-node directory.

## Content is supplied at converge time

`static_site_source_dir` has **no default**. It is the control-node directory
whose contents become the document root. The role fails its first task with an
actionable message when it is unset or does not point at a directory, rather
than publishing an empty site.

Site content is never committed to this repository.

## Installation

The role is not wired into `playbooks/site.yml`: it has no inventory group of
its own, and a site-wide run would fail on the missing content source. Call it
from a playbook that supplies both the hosts and the content directory.

Prerequisites:

- A Debian or Ubuntu LXC reachable from the inventory, able to install `nginx`
  from its distro repository.
- A built site directory on the control node.

Install the collection dependencies once:

```sh
ansible-galaxy collection install -r requirements.yml
```

## Usage

```sh
ansible-playbook -i inventory/hosts.yml <your-playbook>.yml \
  -e static_site_source_dir=/path/to/built/site
```

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `static_site_source_dir` | *(none — required)* | Control-node directory whose contents are mirrored to the document root |
| `static_site_root` | `/var/www/static-site` | Document root on the target |
| `static_site_port` | `80` | Plain-HTTP listen port |
| `static_site_server_name` | `_` | nginx `server_name` (catch-all by default) |
| `static_site_vhost_name` | `static-site` | Vhost filename under `sites-available` |
| `static_site_index` | `index.html` | Directory index and client-side-routing fallback |
| `static_site_error_page` | `404.html` | Custom error document, used only if present at the root of the synced content |
| `static_site_asset_extensions` | css, js, json, svg, woff2, … | Extensions served strictly from disk (a miss is a real 404) |
| `static_site_gzip_types` | text/css, application/json, image/svg+xml, … | Response types compressed on the wire |
| `static_site_gzip_min_length` | `1024` | Smallest response worth compressing, in bytes |
| `static_site_manage_service` | `true` | When false, render config but leave the service alone |

## Routing behaviour

- `/` and any unknown path return `static_site_index`, so a single-page app's
  own router resolves its routes (`try_files $uri $uri/ /index.html`).
- Requests whose extension is in `static_site_asset_extensions` resolve
  strictly from disk. A miss returns a real 404 instead of the index shell —
  without that carve-out the routing fallback would answer `200` + HTML for
  every missing asset, hiding broken build output and leaving the custom error
  page unreachable.
- `error_page 404` is emitted only when `static_site_error_page` exists at the
  root of the synced content.

## Hardening

- `server_tokens off` — no nginx version in responses or error pages.
- `autoindex off` — a directory without an index never lists its contents.
- Dotfiles are denied. The deny is declared before the asset rule because nginx
  matches regex locations in source order, so `/.env.js` would otherwise be
  served by the asset rule.
- gzip is on for the text types above; `text/html` is compressed
  unconditionally by nginx and is invalid in `gzip_types`.

MIME types come from the distro's `/etc/nginx/mime.types`. The molecule verify
play asserts the served `Content-Type` for `.svg`, `.js`, `.css`, `.json`, and
`.woff2`, so a distro that got one wrong fails the scenario rather than
shipping a broken header.

## Testing

```sh
molecule test -s static_site
```

The scenario converges the role against a fixture site in
`molecule/static_site/files/site/`, proves idempotence, then asserts the
rendered config, service state, document root, a `200` with the expected body,
the client-side-routing fallback, the real 404 on a missing asset, every MIME
type above, and — negatively — that a dotfile request is denied and that a
directory without an index never returns a listing.
