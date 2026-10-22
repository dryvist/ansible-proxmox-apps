# idrac_kvm_docker

Deploys an HTML5 virtual-console container for each enabled iDRAC target. The
role builds a local viewer image from the vendor base image and the Dell AVCT
client archive configured by `idrac_kvm_docker_avct_artifact_url`; the archive
is not stored in git.

End users open a normal HTTP URL — no JNLP file, local Java, jar-signing dance,
or Firefox MIME handler. The container transcodes the iDRAC framebuffer into
an HTML5 stream.

## Credentials

`inventory/group_vars/idrac_kvm_group.yml` reads target credentials from the
prefetched `bao_apps_secrets` fact. Each target uses target-prefixed `host`,
`user`, and `password` fields so the flat domain merge does not overwrite
another target. All targets are disabled by default; an enabled target must
have its credential fields in the prefetch result.

The role asserts credentials for enabled targets, writes them to a root-owned
`.env` file with mode `0600`, and passes those values to Compose. The account
must be provisioned separately with only iDRAC login and console-redirection
privileges.

## Installation

The role is wired into `playbooks/site.yml` and runs on hosts in
`idrac_kvm_group`. Target configuration is declared in
`inventory/group_vars/idrac_kvm_group.yml`; credentials come from the
prefetched `bao_apps_secrets` fact. Only enabled targets are rendered,
deployed, and health-checked.

Prerequisites:

- The console guests exist and are reachable.
- The Dell AVCT client artifact is staged in private storage and
  `idrac_kvm_docker_avct_artifact_url` is set (see "Viewer image" below).
- The `community.docker` Ansible collection is installed with
  `python3 scripts/install_galaxy_requirements.py` from the repo root.

The role installs Docker CE + Compose plugin, `fuse-overlayfs` for ZFS-backed
LXC hosts, and a Python venv for the `community.docker` modules on the target
host. It is idempotent across runs.

## Deploy

The normal site converge runs through Semaphore. For a scoped local run, use
the repository's wrapper so inventory loading and OpenBao prefetch run:

```sh
scripts/run-ansible.sh playbooks/site.yml \
  --tags idrac_kvm_docker --limit idrac_kvm_group,localhost
```

Install the `community.docker` collection with
`python3 scripts/install_galaxy_requirements.py` before running the play.

Other useful site tags, using the same wrapper and OpenBao prefetch:

```sh
# Also runs anything else tagged 'idrac'.
scripts/run-ansible.sh playbooks/site.yml --tags idrac

# Out-of-band management slice.
scripts/run-ansible.sh playbooks/site.yml --tags oob,management
```

## Access

After a successful run on the KVM container, each server's HTML5 console is
served on its own port at that container's address:

| Server | Port   | Container    |
| ------ | ------ | ------------ |
| R410   | `5410` | `idrac-r410` |
| R710   | `5710` | `idrac-r710` |

Credentials are supplied to the viewer from the root-owned `.env` file (mode
`0600`); the HTML5 page has no separate login screen.

## Viewer image (Dell AVCT client)

The stock `domistyle/idrac6` image does **not** ship Dell's proprietary AVCT KVM
client (`avctKVM.jar`, `avctKVMIOLinux64.jar`, `avctVMLinux64.jar`,
`libavctKVMIO.so`, `libavmlinux.so`, signed `META-INF`). Without it the HTML5
viewer cannot connect. This role rebuilds a small local image instead:

- `templates/Dockerfile.j2` → `FROM domistyle/idrac6` + `COPY app/ /app/`.
- The `app/` payload is fetched at build time from
  `idrac_kvm_docker_avct_artifact_url` (a tar archive whose top level is `app/`),
  staged in private storage (the object-storage `idrac` bucket / NAS) — it is
  **never** committed to git.
- The image is tagged `idrac_kvm_docker_image` (default `idrac6-avct:local`) and
  compose runs it with `pull: never` (local-only tag).

The R410 and R710 clients are byte-identical, so one image serves both. To
refresh the client, replace the artifact and remove `idrac_kvm_docker_build_dir`
(or the image) before re-running.

The console account has IPMI access set to `none` by design, so power, SEL, and
sensor CLI access through this guest no longer exists. Use the operator's own
admin credentials from the workstation for those operations instead.

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

- `inventory/group_vars/idrac_kvm_group.yml` — declares each target and reads
  its credentials from prefetched `bao_apps_secrets`; only enabled targets are
  rendered, deployed, and health-checked.
- `defaults/main.yml` — `idrac_kvm_docker_targets` defaults to an empty list;
  inventory supplies the target configuration.
- `templates/docker-compose.yml.j2` — generates one service block per enabled
  target. Each service binds `${bind_address}:<host_port>:5800` (5800 is the
  upstream image's HTML5 port; the host-side port differentiates iDRACs).
- `templates/env.j2` — writes credentials for enabled targets to `.env` with
  mode `0600`, root:root. Docker Compose auto-loads it for `${VAR}` substitution.
- `tasks/main.yml` — validates enabled-target credentials → Docker install
  (with `fuse-overlayfs` for ZFS-backed LXC) → data dir → image build → Compose
  and `.env` templates → Python venv for the `community.docker` collection →
  `docker_compose_v2` deploy → port and HTTP health checks.

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

## Variables

- `idrac_kvm_docker_targets` — target list in
  `inventory/group_vars/idrac_kvm_group.yml`; only entries with `enabled: true`
  are rendered, deployed, and health-checked.
- `idrac_kvm_docker_avct_artifact_url` and
  `idrac_kvm_docker_avct_artifact_sha256` — source and integrity pin for the
  viewer client archive.
- `idrac_kvm_docker_data_dir` and `idrac_kvm_docker_build_dir` — on-guest
  Compose and build directories.
