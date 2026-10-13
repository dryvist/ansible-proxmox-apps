# Git mirror role

Deploys two read-only smart HTTP repositories on a Debian LXC:

- /public serves public repositories for the approved GitHub owners without credentials.
- /all serves those public repositories plus private repositories from the two approved work accounts. Its separate listener requires HTTP basic authentication.

Git mirrors are bare repositories refreshed every six hours by a systemd timer.
The sync unit requests short-lived, read-only GitHub App installation tokens
from OpenBao for each configured owner. Tokens are passed to Git as process-only
HTTP headers; clone URLs and repository configuration remain credential-free.

## Requirements

- Debian-based LXC with systemd.
- A read-only OpenBao AppRole for the sync agent, with access to the configured GitHub installation-token permission sets.
- OpenBao Apps secret git_mirror_all_password for the protected HTTP basic-auth account.
- Reverse-proxy routes that publish the two listeners separately, with /all limited to trusted client networks.

## Installation

The git-mirror inventory tag selects the guest.
playbooks/site/01-baseline-infra.yml installs this role and derives its
reverse-proxy source addresses from published inventory.

The GitHub installation must expose only the approved repository owners. The
role also filters API results against its owner list and keeps private
repositories only for the configured accounts.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| git_mirror_installations | Three fixed owner/token-path pairs | OpenBao read-only token mint paths and private repository policy. |
| git_mirror_all_username | mirror | Basic-auth username for /all. |
| git_mirror_all_password | Empty | Required generated password from secret/apps/git-mirror. |
| git_mirror_proxy_sources | [] | Reverse-proxy listener addresses allowed through UFW. |
| git_mirror_public_port | 8080 | Backend port for /public. |
| git_mirror_all_port | 8081 | Backend port for authenticated /all. |
| git_mirror_sync_interval | 6h | Systemd refresh cadence. |

## Read-only and monitoring behavior

The role sets system Git configuration http.receivepack=false. Apache serves
the public and authenticated roots from separate virtual hosts. The sync
wrapper exports git_mirror_sync_success and
git_mirror_sync_last_success_timestamp_seconds through the node_exporter
textfile collector.

The initial converge performs a sync and checks the public and authenticated
repository endpoints. The recurring timer records failures in the metrics file
and preserves the last successful timestamp.
