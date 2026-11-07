# verdaccio_cache

Runs a native Verdaccio npm registry mirror. Reads are public; package
publishing and user registration are disabled.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `verdaccio_cache_version` | `6.11.1` | Exact Verdaccio release installed by npm. |
| `verdaccio_cache_node_version` | `22.23.4` | Exact Node.js LTS runtime release. |
| `verdaccio_cache_port` | `4873` | Listening TCP port. |
| `verdaccio_cache_storage_dir` | `/var/lib/verdaccio/storage` | Pull-through package data. |

Verdaccio 6.11.1 was released on 2026-10-24: [official release](https://github.com/verdaccio/verdaccio/releases/tag/v6.11.1).
Node.js 22.23.4 was released on 2026-10-21: [official release](https://nodejs.org/en/blog/release/v22.23.4).
The npm install only selects dependency releases available on or before 2026-11-04.

shortcut: no byte cap upstream; the data is a disposable pull-through cache; if the guest's disk alert fires, stop the service and clear this directory.
