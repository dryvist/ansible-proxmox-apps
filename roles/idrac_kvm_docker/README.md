# idrac_kvm_docker

Runs both `domistyle/idrac6`-based viewers (one Docker container per physical
iDRAC) on a single dedicated Docker-in-LXC (`idrac-kvm`, LXC 251), exposes each
HTML5-rendered KVM viewer on a per-iDRAC host port, and installs `ipmitool` for
non-Java chassis operations.

End users hit the viewer at a normal HTTP URL — no JNLP file, no local Java,
no jar-signing dance, no Firefox MIME handler. The container transcodes the
iDRAC framebuffer to a browser-renderable HTML5 stream. Note: the upstream
`domistyle/idrac6` image does NOT ship Dell's AVCT KVM client; this role bakes
it in via a local image rebuild (see "Viewer image" below).

## Installation

The role is wired into `playbooks/site.yml` (Phase 7b) and runs against any
host in `idrac_kvm_group`. The group is populated by `inventory/load_tofu.yml`
from `containers` tagged `idrac` in the OpenTofu inventory (see terraform-proxmox
LXC 251 `idrac-kvm`), reached over `proxmox_pct_remote`.

Prerequisites:

- LXC 251 `idrac-kvm` exists (OpenTofu-managed; tags include `container` and `idrac`).
- Your Doppler config populated with all six
  `IDRAC_R410_*` / `IDRAC_R710_*` variables (see Secrets table below).
- The Dell AVCT client artifact staged in private storage and
  `idrac_kvm_docker_avct_artifact_url` set (see "Viewer image" below).
- `community.docker` Ansible collection installed (`ansible-galaxy collection
  install -r requirements.yml` from the repo root).

The role installs Docker CE + Compose plugin, `fuse-overlayfs` for ZFS-backed
LXC hosts, `ipmitool`, and a Python venv for the `community.docker` modules
on the target host. It is idempotent across runs.

## Usage

Deploy or update both iDRAC containers:

```sh
# From the ansible-proxmox-apps repo root, with Doppler env loaded:
doppler run -- \
  ansible-playbook playbooks/site.yml --tags idrac_kvm_docker
```

Other useful tag invocations (all defined in `site.yml` Phase 7b):

```sh
# Same effect via the broader tag — also runs anything else tagged 'idrac':
doppler run -- \
  ansible-playbook playbooks/site.yml --tags idrac

# Out-of-band management slice (idrac + future iLO/IPMI roles):
doppler run -- \
  ansible-playbook playbooks/site.yml --tags oob,management
```

The role asserts all six Doppler env vars are non-empty before doing any work
and fails fast with a Doppler pointer if any are missing.

## Access

After a successful run on LXC 251 (IP 10.0.1.251):

| Server | URL                       | Container    |
| ------ | ------------------------- | ------------ |
| R410   | `http://10.0.1.251:5410/` | `idrac-r410` |
| R710   | `http://10.0.1.251:5710/` | `idrac-r710` |

Credentials are baked into the container via `.env` and forwarded to the
iDRAC by the bundled viewer — no separate login screen on the HTML5 page.

## Viewer image (Dell AVCT client)

The stock `domistyle/idrac6` image does **not** ship Dell's proprietary AVCT KVM
client (`avctKVM.jar`, `avctKVMIOLinux64.jar`, `avctVMLinux64.jar`,
`libavctKVMIO.so`, `libavmlinux.so`, signed `META-INF`). Without it the HTML5
viewer cannot connect. This role rebuilds a small local image instead:

- `templates/Dockerfile.j2` → `FROM domistyle/idrac6` + `COPY app/ /app/`.
- The `app/` payload is fetched at build time from
  `idrac_kvm_docker_avct_artifact_url` (a tar archive whose top level is `app/`),
  staged in private storage (MinIO/NAS) — it is **never** committed to git.
- The image is tagged `idrac_kvm_docker_image` (default `idrac6-avct:local`) and
  compose runs it with `pull: never` (local-only tag).

The R410 and R710 clients are byte-identical, so one image serves both. To
refresh the client, replace the artifact and remove `idrac_kvm_docker_build_dir`
(or the image) before re-running.

## CLI Fallback (ipmitool)

When the KVM viewer is overkill (or stuck), SSH to VM 251 and hit the iDRAC's
IPMI-over-LAN endpoint directly. The role installs `ipmitool` on the VM.

```sh
ssh debian@<vm-251-ip>

# Use the values from /opt/idrac-kvm/.env. Example for R410:
. /opt/idrac-kvm/.env   # exports IDRAC_R410_HOST/USER/PASSWORD etc.
ipmitool -I lanplus -H "$IDRAC_R410_HOST" -U "$IDRAC_R410_USER" -P "$IDRAC_R410_PASSWORD" chassis power status
ipmitool -I lanplus -H "$IDRAC_R410_HOST" -U "$IDRAC_R410_USER" -P "$IDRAC_R410_PASSWORD" chassis power on|off|cycle|reset
ipmitool -I lanplus -H "$IDRAC_R410_HOST" -U "$IDRAC_R410_USER" -P "$IDRAC_R410_PASSWORD" sel list
ipmitool -I lanplus -H "$IDRAC_R410_HOST" -U "$IDRAC_R410_USER" -P "$IDRAC_R410_PASSWORD" sensor list
```

The `.env` file is mode-`0600`, root-owned; `sudo` the source line above.

## iDRAC-side Prerequisites

iDRAC 6 has a few well-known footguns that block the viewer regardless of
which client is used. Check these on the iDRAC web UI before assuming the
container is broken:

- **Firmware** ≥ 2.92 (R410). Pre-2.85 builds have viewer-handshake bugs
  with modern Java that no container fix can paper over.
- **Console/Media → Configuration → "Encrypt Video Output"** must match
  what the bundled viewer negotiates. If the KVM tears down right after
  ProtocolAPCP version negotiation with a generic "Connection failed",
  flip this setting and retry — it is the single most common cause of
  late-stage connection failures.
- **System → Sessions** — terminate stale console sessions before retrying.
  Failed launches sometimes leave session slots held open.

## How It's Built

- `defaults/main.yml` — `idrac_kvm_docker_targets` list (one entry per iDRAC:
  name, host_port, env_prefix). Add iDRACs by appending an entry; the
  compose template loops over them.
- `templates/docker-compose.yml.j2` — generates one service block per target.
  Each service binds `${bind_address}:<host_port>:5800` (5800 is the upstream
  image's HTML5 port; the host-side port differentiates iDRACs).
- `templates/env.j2` — writes `${PREFIX}_HOST`, `${PREFIX}_USER`,
  `${PREFIX}_PASSWORD` triples for every target. Mode `0600`, root:root.
  Docker Compose auto-loads it for `${VAR}` substitution.
- `tasks/main.yml` — Doppler env assertion → Docker install (with
  `fuse-overlayfs` for ZFS-backed LXC) → ipmitool install → data dir →
  compose + .env templates → Python venv for the `community.docker` collection
  → `docker_compose_v2` deploy → port + HTTP health checks.

## Why domistyle/idrac6 over a Mac-side webtop

A Mac-side OrbStack variant lives at `orbstack-kubernetes/docker/idrac-webtop`
in the sibling repo. It runs an XFCE desktop + Firefox + OpenWebStart + a
custom `idrac-launch` wrapper that downloads and self-signs the AVCT KVM
jars to bypass IcedTea-Web's hard-coded `SecurityDelegateImpl` check on
unsigned jars-with-all-permissions. It works as far as launching the viewer,
but is not the canonical deploy: it requires a Mac host, depends on Rosetta
for x86_64 native libs, and pushes JNLP handling onto the end user.

`domistyle/idrac6` eliminates all of that — it runs a known-good legacy
Java stack inside the container and exposes a plain HTTP endpoint. The
orbstack-kubernetes variant is retained as an exploratory record only.

## Secrets

| Variable                | Source                          |
| ----------------------- | ------------------------------- |
| `IDRAC_R410_HOST`       | Doppler                         |
| `IDRAC_R410_USER`       | Doppler                         |
| `IDRAC_R410_PASSWORD`   | Doppler                         |
| `IDRAC_R710_HOST`       | Doppler                         |
| `IDRAC_R710_USER`       | Doppler                         |
| `IDRAC_R710_PASSWORD`   | Doppler                         |

None of these are ever committed to git. The role's first task asserts they
are all set and fails fast with a pointer to Doppler.
