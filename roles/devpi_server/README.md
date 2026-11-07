# devpi_server

Runs a native devpi-server PyPI mirror. The default index mirrors PyPI on
demand; mutations are restricted to the local `root` account. Initialization
sets an unrecorded random root password so the public mirror does not retain
devpi's empty default root password.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `devpi_server_version` | `6.21.0` | Exact devpi-server release installed in the role virtual environment. |
| `devpi_server_port` | `3141` | Listening TCP port. |
| `devpi_server_bind_address` | `0.0.0.0` | Listening address. |
| `devpi_server_venv` | `/opt/devpi-server` | Isolated Python environment. |
| `devpi_server_data_dir` | `/var/lib/devpi-server` | Persistent mirror and index data. |

The pinned devpi-server release was published on 2026-10-27, more than three
days before this role was authored: [PyPI release](https://pypi.org/project/devpi-server/6.21.0/).

shortcut: no byte cap upstream; the data is a disposable pull-through cache; if the guest's disk alert fires, stop the service and clear this directory.
