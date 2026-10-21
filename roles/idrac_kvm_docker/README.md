# idrac_kvm_docker

Deploys an HTML5 virtual-console container for each enabled iDRAC target. The
role builds a local viewer image from the vendor base image and the Dell AVCT
client archive configured by `idrac_kvm_docker_avct_artifact_url`; the archive
is not stored in git.

## Credentials

`inventory/group_vars/idrac_kvm_group.yml` reads target credentials from the
prefetched `bao_apps_secrets` fact. The apps domain reads the KV paths
`secret/apps/idrac-kvm-r410` and `secret/apps/idrac-kvm-r710`; each path uses
target-prefixed `host`, `user`, and `password` fields so the flat domain merge
does not overwrite another target. R410 is enabled, and R710 remains disabled.

The role asserts credentials for enabled targets, writes them to a root-owned
`.env` file with mode `0600`, and passes those values to Compose. The account
must be provisioned separately with only iDRAC login and console-redirection
privileges; the viewer role does not install an IPMI CLI fallback.

## Deploy

The normal site converge runs through Semaphore. For a scoped local run, use
the repository's wrapper so inventory loading and OpenBao prefetch run:

```sh
scripts/run-ansible.sh playbooks/site.yml \
  --tags idrac_kvm_docker --limit idrac_kvm_group,localhost
```

Install the `community.docker` collection with
`python3 scripts/install_galaxy_requirements.py` before running the play.

## Variables

- `idrac_kvm_docker_targets` — target list in
  `inventory/group_vars/idrac_kvm_group.yml`; only entries with `enabled: true`
  are rendered, deployed, and health-checked.
- `idrac_kvm_docker_avct_artifact_url` and
  `idrac_kvm_docker_avct_artifact_sha256` — source and integrity pin for the
  viewer client archive.
- `idrac_kvm_docker_data_dir` and `idrac_kvm_docker_build_dir` — on-guest
  Compose and build directories.
