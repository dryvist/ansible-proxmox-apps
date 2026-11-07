# raw_cache

Runs a native Nginx cache for configured HTTPS download origins. Requests use
`/<name>/<upstream-path>`; HTTPS redirects are followed inside Nginx and the
result is cached under the complete original upstream URL. Logs go to
journald through the local syslog socket.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `raw_cache_nginx_version` | `1.30.6` | Exact Nginx stable release. |
| `raw_cache_port` | `8080` | Listening TCP port. |
| `raw_cache_cache_max_size` | `20g` | Nginx cache size ceiling. |
| `raw_cache_cache_dir` | `/var/cache/raw-cache` | Bounded Nginx cache directory. |
| `raw_cache_upstreams` | GitHub raw, GitHub releases, Hermes assets | Named HTTPS origins served by this cache. |
| `raw_cache_resolvers` | `ansible_dns.nameservers` | DNS servers used for redirect targets. |

Nginx 1.30.6 was released on 2026-10-14, more than three days before this
role was authored: [official stable release](https://nginx.org/en/CHANGES-1.30).
The role installs the matching exact `nginx.org` Debian package for bookworm
or trixie and checks the repository signing key fingerprint.
