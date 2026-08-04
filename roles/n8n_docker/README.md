# n8n_docker

Deploys the n8n workflow engine as a single app container in an LXC. Its
database is the shared PostgreSQL cluster, not a colocated service.

## Installation

This role ships in the `ansible-proxmox-apps` repository and is applied via
`playbooks/site.yml`. No separate installation is required beyond cloning the
repo and installing collection dependencies:

```bash
git clone https://github.com/dryvist/ansible-proxmox-apps.git
cd ansible-proxmox-apps
ansible-galaxy collection install -r requirements.yml
```

## Prerequisites

- An LXC tagged `n8n` (nesting enabled for Docker).
- The shared PostgreSQL cluster converged first, so this app's database and
  login role exist. Both live in `inventory/group_vars/postgres_group.yml`.
- The secret store reachable, or the corresponding env fallbacks present. The
  key below is the one value the role refuses to proceed without.

## Usage

```bash
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook playbooks/site.yml --tags n8n_docker'
```

## Why the database is not in this stack

Workflow definitions, stored credentials and execution history are the whole
value of this app, and none of it is reconstructible from configuration. The
shared cluster already carries continuous WAL archiving, point-in-time
recovery, and nightly logical dumps. A database running beside the app inherits
none of that, and a database on a mount the guest-level backup mechanism cannot
capture has no backup at all.

## The encryption key

`N8N_ENCRYPTION_KEY` encrypts every credential stored in the database. Two
properties follow, and both are load-bearing:

- **It is part of the backup.** A database restored without the matching key
  yields workflows whose every stored credential is permanently undecryptable.
  Nothing errors: the app starts, the workflows are listed, and the failure
  surfaces only when one runs.
- **It must not live only beside the data it unlocks.** Its canonical home is
  the secret store; the generate-once file on the guest is the greenfield
  bootstrap and a local fallback, nothing more.

The role resolves the key from the secret store first, then the guest, and
**asserts a non-empty result before deploying**. It never generates a
replacement for an install that already has one.

## Cutover from a colocated database

Ordered so a failure at any step leaves the previous step intact and the app
recoverable by reverting this role's version. Steps 1-2 change nothing the
running app can see.

1. **Capture the key into the secret store.** Read the existing key off the
   guest, carry it in the converge environment, and converge the secret-store
   role so it is promoted. Verify it reads back before going further — this is
   the only step whose omission is unrecoverable later.
2. **Create the database and role on the shared cluster.** Converge the
   database role; the app is still pointed at its old database and is
   unaffected. The new database is empty.
3. **Quiesce and dump.** Stop the app only (leave its old database running),
   then take a logical dump of the old database. The app being down bounds the
   work; the old database is still intact and is the rollback.
4. **Load into the shared cluster.** Restore the dump into the database from
   step 2. If this fails, nothing has changed for the app: revert the role
   version and restart it against the old database.
5. **Repoint and converge.** Converge this role at its current version. The app
   comes up against the shared cluster with the key from step 1.
6. **Verify before reclaiming anything.** Confirm workflows are present AND
   that a workflow using a stored credential actually executes — the second
   check is the one that proves the key survived. Only then retire the old
   database's data.

The old database's data directory is deliberately left in place by this role.
It is the rollback for steps 3-6 and should be removed as a separate, deliberate
action after step 6 passes, never as part of the cutover.
