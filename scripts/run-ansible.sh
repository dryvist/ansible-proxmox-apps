#!/usr/bin/env bash
# Ansible runner — prefers a short-lived SSH certificate from the OpenBao CA
# (ssh-certificate-authority ADR) over the shared static key, then runs the
# playbook. Invoke under your secrets manager so BAO_ADDR + the
# ansible-converge AppRole are ambient:
#   doppler run -- scripts/run-ansible.sh playbooks/site.yml [args...]
# Without those env vars the static PROXMOX_SSH_KEY_PATH flow is unchanged.
set -euo pipefail

usage() {
  echo "Usage: $0 <playbook> [ansible-playbook args...]"
  echo "Example: doppler run -- $0 playbooks/site.yml --limit vms"
  exit 1
}

[[ $# -lt 1 ]] && usage

PLAYBOOK="$1"
shift

# A converge from a checkout behind its remote branch deploys stale content
# and still exits 0 with a green play recap — nothing in the output
# distinguishes it from a real deployment. Refuse by default; ALLOW_STALE_CHECKOUT=1
# is the deliberate escape hatch for a pinned replay.
# Detached HEAD (how CI checks out a specific commit) isn't the stale-developer-
# checkout case this guards against — there's no tracked branch to compare
# against, so skip rather than fail on `git rev-parse origin/HEAD` nonsense.
REPO_ROOT=$(git rev-parse --show-toplevel)
BRANCH=$(git -C "$REPO_ROOT" symbolic-ref -q --short HEAD || true)
if [[ -n $BRANCH ]]; then
  git -C "$REPO_ROOT" fetch --quiet origin "$BRANCH"
  LOCAL_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
  REMOTE_SHA=$(git -C "$REPO_ROOT" rev-parse "origin/$BRANCH")
  if [[ $LOCAL_SHA != "$REMOTE_SHA" ]] && [[ -z ${ALLOW_STALE_CHECKOUT:-} ]]; then
    # Report the divergence honestly. A checkout that is AHEAD of origin has
    # zero commits behind it, and reporting that as "0 commit(s) behind —
    # refusing" reads as a bug in the guard rather than a fact about the
    # checkout, which invites setting ALLOW_STALE_CHECKOUT to make the noise
    # stop. That converges unpushed, unreviewed local commits — the exact
    # outcome this guard exists to prevent.
    BEHIND=$(git -C "$REPO_ROOT" rev-list --count "$LOCAL_SHA..$REMOTE_SHA")
    AHEAD=$(git -C "$REPO_ROOT" rev-list --count "$REMOTE_SHA..$LOCAL_SHA")
    echo "ERROR: checkout does not match origin/$BRANCH ($BEHIND behind, $AHEAD ahead) — refusing to converge." >&2
    echo "  local:  $LOCAL_SHA" >&2
    echo "  remote: $REMOTE_SHA" >&2
    if [[ $AHEAD -gt 0 ]]; then
      echo "Push the local commit(s) so what converges is what was reviewed: git push origin $BRANCH" >&2
    else
      echo "Run 'git pull --ff-only origin $BRANCH', or set ALLOW_STALE_CHECKOUT=1 for a deliberate pinned replay." >&2
    fi
    exit 1
  fi
fi

# The SHA check above only proves the CHECKED-OUT COMMIT matches origin — it
# is blind to uncommitted edits to tracked files, which deploy content that
# matches neither the remote nor a clean checkout of that commit and still
# exit 0 with a green recap, same failure shape the SHA check exists for.
# --untracked-files=no: this repo carries untracked working state (a
# published tofu-inventory cache, a resolved shared role) that is not
# playbook drift, so counting it would refuse every routine run.
if [[ -n $(git -C "$REPO_ROOT" status --porcelain --untracked-files=no) ]] && [[ -z ${ALLOW_STALE_CHECKOUT:-} ]]; then
  echo "ERROR: working tree has uncommitted changes to tracked files — refusing to converge from unreviewed local edits." >&2
  echo "Commit or stash them, or set ALLOW_STALE_CHECKOUT=1 for a deliberate override." >&2
  exit 1
fi

# The media stack lives in a pinned submodule that site.yml converges as its
# own process. Checking it out here means a bare clone converges the whole
# estate with no preparatory step; `--init` takes the recorded SHA, never a
# branch tip. Failing loudly beats converging a partial estate silently.
# Best-effort, not fatal: a checkout without access to the submodule must still
# be able to run every other playbook. site.yml's media play checks for the
# checkout itself and fails there, where the consequence is actually media.
#
# --checkout is what makes this work at all now. .gitmodules marks the
# submodule `update = none`, because Semaphore clones a repository with an
# unconditional `git submodule update --init --recursive` it offers no way to
# disable, and that step is fatal: one private submodule the execution plane
# cannot read failed EVERY template at clone time, before any playbook ran.
# `update = none` makes that step skip it; --checkout overrides the setting
# here, so a caller that CAN read the submodule still gets it and still warns
# when the checkout fails.
if [[ -f .gitmodules ]] && ! git submodule update --init --recursive --checkout; then
  echo "run-ansible: submodule checkout failed — the media stack will not converge" >&2
fi

CERT_DIR=""
RUNNER_BAO_TOKEN=""

revoke_runner_token() {
  [[ -z $RUNNER_BAO_TOKEN ]] && return 0
  { set +x; } 2>/dev/null
  if BAO_TOKEN=$RUNNER_BAO_TOKEN BAO_CLIENT_TIMEOUT=10 bao token revoke -self >/dev/null 2>&1; then
    RUNNER_BAO_TOKEN=""
    return 0
  fi
  return 1
}

# shellcheck disable=SC2329 # false positive: invoked via `trap cleanup EXIT` below.
# Reproduced in isolation — shellcheck stops crediting the trap reference once
# the script ends in an explicit `exit`, which the run log below now does.
cleanup() {
  local status=$?
  revoke_runner_token || true
  [[ -n $CERT_DIR ]] && rm -rf "$CERT_DIR"
  return "$status"
}
trap cleanup EXIT

# Mint an ephemeral ed25519 keypair signed by ssh-client-ca/sign/
# automation-ansible (principal `ansible`, TTL <=1h) or, when the caller is
# the execution plane itself, sign/automation-semaphore (principal
# `semaphore`) — see CONVERGE_SIGN_ROLE below. The plane's own principal makes
# a plane-run converge distinguishable from every other caller in sshd logs.
# OpenSSH pairs id + id-cert.pub automatically via PROXMOX_SSH_KEY_PATH. No
# secret material on any command line.
mint_ssh_cert() {
  local mount=${SSH_CA_MOUNT:-ssh-client-ca}
  CERT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ansible-sshcert.XXXXXX") || return 1
  chmod 700 "$CERT_DIR"
  (umask 077 && ssh-keygen -q -t ed25519 -N '' -C "ansible-converge" -f "$CERT_DIR/id") || return 1
  { set +x; } 2>/dev/null
  # secret_id is read from stdin (`secret_id=-`), never passed as an argument:
  # every process on the host can read another's argv.
  # Return 2 specifically for a refused LOGIN (as opposed to a signing
  # failure) so the caller can tell "this identity is not accepted here" from
  # every other mint failure and fall back to the next identity in order.
  RUNNER_BAO_TOKEN=$(printf '%s' "$CONVERGE_SECRET_ID" \
    | BAO_CLIENT_TIMEOUT=10 bao write -field=token auth/approle/login \
      role_id="$CONVERGE_ROLE_ID" secret_id=-) || return 2
  # 2h, matching the automation-ansible signing role's ceiling. At 1h a full
  # converge outlived its own certificate and every remaining host reported
  # "Failed to authenticate" — an elapsed credential wearing the costume of a
  # broken one. A request above the role's ceiling is refused outright, so this
  # value and openbao_ssh_roles must move together.
  BAO_TOKEN=$RUNNER_BAO_TOKEN BAO_CLIENT_TIMEOUT=10 \
    bao write -field=signed_key "$mount/sign/$CONVERGE_SIGN_ROLE" \
    public_key=@"$CERT_DIR/id.pub" ttl="${SSH_CERT_TTL:-2h}" \
    > "$CERT_DIR/id-cert.pub" || return 1
  export PROXMOX_SSH_KEY_PATH="$CERT_DIR/id"

  if [[ -z ${BAO_TOKEN:-} ]]; then
    # The inventory resolver and controller-side OpenBao reads share this
    # short-lived token. Cleanup revokes it after ansible-playbook exits.
    export BAO_TOKEN=$RUNNER_BAO_TOKEN
  else
    # A caller-supplied token may carry broader human policy. Preserve it and
    # revoke the runner-owned signing token as soon as the cert is minted.
    revoke_runner_token || true
  fi
}

# The store role logs in for itself, at the point it reconciles, so this wrapper
# neither mints nor holds a reconcile token.
#
# Minting here instead put the login at the start of the run while the store play
# executes over an hour later, and the role's token lives 30 minutes. The token
# was therefore expired before its first use, and the store answers an expired
# token with the same `403 permission denied` it uses for a policy denial -- so
# the fault read as a missing grant the identity has always had. Raising the
# lifetime to cover the gap would make the credential longer-lived to accommodate
# a scheduling defect, and would fail again the first time a run outgrew it.
#
# An absent credential is NOT an error here, and the contract tests assert that:
# a workstation caller supplies reconcile secret-zero to the role directly, and
# the role itself refuses loudly when it is configured but cannot authenticate.
# Say which case this is so a silent skip on the plane stays impossible.
if [[ -n ${BAO_ADDR:-} ]] &&
   [[ -z ${OPENBAO_APPROLE_OPENBAO_RECONCILE_ROLE_ID:-} ||
      -z ${OPENBAO_APPROLE_OPENBAO_RECONCILE_SECRET_ID:-} ]]; then
  echo "run-ansible: no reconcile identity in this environment; the store" >&2
  echo "  role will fall back to reconcile secret-zero, or skip and say so." >&2
fi

# WHICH IDENTITY THIS CONVERGE AUTHENTICATES AS.
#
# Two AppRoles carry an identical grant — the converge policy, config
# authorship, and the automation-ansible signing role. One is declared and
# bounded: a one-day secret_id, a redemption cap, and a source-address
# restriction to the internal segments. The other is declared nowhere and
# bounded on no axis at all — it never expires, redeems without limit, and is
# accepted from any address that can reach the endpoint.
#
# This wrapper read the unbounded one. Its own certificate label and the
# comments around it name the bounded one. Measured on the store's audit log:
# the bounded identity's last login was 2026-09-06 04:09, and every converge
# since has authenticated as the unbounded shadow of it — a bound that lapsed
# and fell through to a standing credential, with nothing anywhere reporting a
# failure.
#
# Preference, not a hard switch, because the bounded credential is not yet
# published everywhere this script runs. The fallback is deliberately LOUD: a
# silent one is how this went unnoticed for three days.
#
# A third pair, OPENBAO_APPROLE_SEMAPHORE_*, belongs to the unattended
# execution plane itself rather than to any human-run checkout. It carries
# the same converge grant plus its own delta and signs under its own CA role,
# so a plane-run converge is distinguishable from every other caller in sshd
# logs by principal alone. Preferred first when present.
# select_converge_identity fills CONVERGE_ROLE_ID/SECRET_ID/IDENTITY/SIGN_ROLE
# from the first candidate present, skipping any tier whose AppRole login was
# already refused this run (SKIP_SEMAPHORE / SKIP_ANSIBLE_CONVERGE, set by the
# retry loop below). Callable more than once so a refused login can fall
# through to the next tier without duplicating the selection logic.
select_converge_identity() {
  CONVERGE_ROLE_ID=""
  CONVERGE_SECRET_ID=""
  CONVERGE_IDENTITY=""
  CONVERGE_SIGN_ROLE="automation-ansible"
  if [[ -z ${SKIP_SEMAPHORE:-} && -n ${OPENBAO_APPROLE_SEMAPHORE_ROLE_ID:-} && -n ${OPENBAO_APPROLE_SEMAPHORE_SECRET_ID:-} ]]; then
    CONVERGE_ROLE_ID=$OPENBAO_APPROLE_SEMAPHORE_ROLE_ID
    CONVERGE_SECRET_ID=$OPENBAO_APPROLE_SEMAPHORE_SECRET_ID
    CONVERGE_IDENTITY="semaphore (execution plane)"
    CONVERGE_SIGN_ROLE="automation-semaphore"
  elif [[ -z ${SKIP_ANSIBLE_CONVERGE:-} && -n ${OPENBAO_APPROLE_ANSIBLE_CONVERGE_ROLE_ID:-} && -n ${OPENBAO_APPROLE_ANSIBLE_CONVERGE_SECRET_ID:-} ]]; then
    CONVERGE_ROLE_ID=$OPENBAO_APPROLE_ANSIBLE_CONVERGE_ROLE_ID
    CONVERGE_SECRET_ID=$OPENBAO_APPROLE_ANSIBLE_CONVERGE_SECRET_ID
    CONVERGE_IDENTITY="ansible-converge (declared, bounded)"
  elif [[ -n ${OPENBAO_APPROLE_ANSIBLE_ROLE_ID:-} && -n ${OPENBAO_APPROLE_ANSIBLE_SECRET_ID:-} ]]; then
    CONVERGE_ROLE_ID=$OPENBAO_APPROLE_ANSIBLE_ROLE_ID
    CONVERGE_SECRET_ID=$OPENBAO_APPROLE_ANSIBLE_SECRET_ID
    CONVERGE_IDENTITY="ansible (UNDECLARED, unbounded)"
    echo "WARNING: converging as an identity that is declared nowhere and bounded" >&2
    echo "  on no axis — no lifetime, no redemption cap, no source restriction —" >&2
    echo "  because the declared equivalent's credential is not in this" >&2
    echo "  environment. Publish OPENBAO_APPROLE_ANSIBLE_CONVERGE_{ROLE,SECRET}_ID" >&2
    echo "  here and this warning goes away. See the identity-swap incident." >&2
  fi
}
select_converge_identity

if [[ -n ${BAO_ADDR:-} && -n $CONVERGE_ROLE_ID && -n $CONVERGE_SECRET_ID ]]; then
  # FAIL-LOUD: when the cert env is present, a mint failure is an error — never
  # silently ride the static key (that masked a dead cert path once already).
  # Break-glass = run WITHOUT the BAO env, with PROXMOX_SSH_KEY_PATH set.
  #
  # A refused LOGIN (mint_ssh_cert returns 2) is not a fatal mint failure — it
  # means this tier's AppRole is not accepted from here (e.g. the semaphore
  # pair's source-address restriction refuses a workstation caller) — so retry
  # with the next tier in order before giving up. Any other mint failure
  # (signing, key generation) still fails loud immediately, unchanged.
  while true; do
    mint_ssh_cert && break
    status=$?
    if [[ $status -ne 2 ]]; then
      echo "ERROR: OpenBao SSH cert mint FAILED and the cert env is present — refusing" >&2
      echo "the silent static-key fallback. Fix the cert path, or unset the OPENBAO_APPROLE_ANSIBLE_*" >&2
      echo "env and set PROXMOX_SSH_KEY_PATH to deliberately use the static break-glass key." >&2
      exit 1
    fi
    echo "WARNING: AppRole login refused for identity: $CONVERGE_IDENTITY — retrying with the next identity in order." >&2
    case $CONVERGE_SIGN_ROLE in
      automation-semaphore) SKIP_SEMAPHORE=1 ;;
      *)
        # Under set -e, a bare `[[ ]] && x=1` that evaluates false would end
        # this case arm on a nonzero status and kill the script — the `if`
        # keeps the arm's own exit status at 0 regardless of the match.
        if [[ $CONVERGE_IDENTITY == ansible-converge* ]]; then
          SKIP_ANSIBLE_CONVERGE=1
        fi
        ;;
    esac
    [[ -n $CERT_DIR ]] && rm -rf "$CERT_DIR"
    CERT_DIR=""
    select_converge_identity
    if [[ -z $CONVERGE_ROLE_ID || -z $CONVERGE_SECRET_ID ]]; then
      echo "ERROR: every OpenBao converge identity was refused — no identity left to try." >&2
      exit 1
    fi
  done
  # The playbook process (and anything it shells out to) inherits the pair
  # that actually authenticated, not just whichever tier was preferred first.
  export CONVERGE_ROLE_ID CONVERGE_SECRET_ID
  # Print the window. A converge that outlives its certificate dies with an
  # UNREACHABLE that reads exactly like a broken host, and the only way to tell
  # the two apart afterwards is knowing when the cert expired.
  echo "Using a short-lived SSH certificate from the OpenBao CA ($CONVERGE_SIGN_ROLE)."
  echo "  authenticated as: $CONVERGE_IDENTITY"
  # `|| true` is load-bearing under `set -euo pipefail`: if ssh-keygen cannot
  # parse the certificate the pipeline fails and takes the whole converge with
  # it. A line that only reports when the credential expires must never be able
  # to end the run it is describing.
  ssh-keygen -Lf "$CERT_DIR/id-cert.pub" 2>/dev/null | sed -n 's/^ *Valid:/  cert /p' || true
elif [[ -z ${PROXMOX_SSH_KEY_PATH:-} ]]; then
  echo "ERROR: no SSH auth available — set BAO_ADDR + OPENBAO_APPROLE_ANSIBLE_* for cert" >&2
  echo "minting, or PROXMOX_SSH_KEY_PATH for the static break-glass key." >&2
  exit 1
fi

# Pin host identities: materialize the reviewed known_hosts (Doppler
# SSH_KNOWN_HOSTS, harvested over authenticated channels) and verify strictly.
# A rebuilt guest gets a new host key and fails closed until re-harvested —
# that is the intended tradeoff. These pinned options are PREPENDED and
# OpenSSH uses the first value per option, so appended caller extras cannot
# weaken them; GlobalKnownHostsFile is disabled so only the pin is consulted.
# Without the pin ambient, non-interactive runs fail closed for any host not
# already in the user's own known_hosts.
if [[ -n ${SSH_KNOWN_HOSTS:-} ]]; then
  if [[ -z $CERT_DIR ]]; then
    CERT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ansible-sshkh.XXXXXX")
    chmod 700 "$CERT_DIR"
  fi
  printf '%s\n' "$SSH_KNOWN_HOSTS" > "$CERT_DIR/known_hosts"
  chmod 600 "$CERT_DIR/known_hosts"
  export ANSIBLE_SSH_COMMON_ARGS="-o UserKnownHostsFile=$CERT_DIR/known_hosts -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=yes${ANSIBLE_SSH_COMMON_ARGS:+ $ANSIBLE_SSH_COMMON_ARGS}"
  # Same file, for tests/inventory_load/verify_inventory.yml's coverage
  # check — the actual materialized pin, not the fixture, on every real run.
  export SSH_KNOWN_HOSTS_FILE="$CERT_DIR/known_hosts"

  # ANSIBLE_SSH_COMMON_ARGS above reaches the OpenSSH transport only: it is
  # appended to an ssh command line, and container hosts are not reached by
  # one. They use proxmox_pct_remote, which builds a paramiko client in
  # process, ignores those options entirely, and reads two fixed paths for
  # host keys — the user's own known_hosts and the system file. The path is
  # hard-coded in the plugin, so there is nothing to point elsewhere; the pin
  # has to be written where it already looks.
  #
  # Until this existed the pin was configured, reviewed, and inert for every
  # container host. That is worse than absent, because it looks enforced. It
  # surfaces as an unattended run trying to PROMPT for an unknown host key and
  # failing with "stdin is not interactive" — a message naming neither host
  # keys nor the connection — and reporting every target UNREACHABLE.
  #
  # Merge rather than overwrite: on a workstation this is the operator's own
  # file. Exact-line dedupe keeps repeated runs idempotent.
  mkdir -p "$HOME/.ssh"
  chmod 700 "$HOME/.ssh"
  touch "$HOME/.ssh/known_hosts"
  chmod 600 "$HOME/.ssh/known_hosts"
  merged=$(mktemp "${TMPDIR:-/tmp}/ansible-kh.XXXXXX")
  awk '!seen[$0]++' "$HOME/.ssh/known_hosts" "$CERT_DIR/known_hosts" > "$merged"
  cat "$merged" > "$HOME/.ssh/known_hosts"
  rm -f "$merged"
fi

# A converge is the highest-consequence thing this repo does; without a
# persisted log, reconstructing what happened after the fact means trusting
# a green recap or digging through unrelated evidence (sshd logins, reflog).
LOG_DIR="$REPO_ROOT/.ansible-run-logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$PLAYBOOK" .yml).log"
echo "Logging this run to $LOG_FILE"
set +e
ansible-playbook "$PLAYBOOK" "$@" 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}
set -e

# A --limit naming a group that matched nothing (bad group name, a group only
# populated by a DIFFERENT repo's inventory loader, a typo) still lets the
# play recap come back green — localhost (the inventory-loader host) always
# ran, so a naive "did anything run" check is never satisfied by absence.
# If --limit asked for anything beyond bare localhost, the recap must show at
# least one non-localhost host, or this run touched nothing it was asked to.
LIMIT_VAL=""
prev=""
for a in "$@"; do
  [[ $prev == "--limit" || $prev == "-l" ]] && LIMIT_VAL="$a"
  [[ $a == --limit=* ]] && LIMIT_VAL="${a#--limit=}"
  prev="$a"
done
NON_LOCALHOST_LIMIT=$(tr ',' '\n' <<<"$LIMIT_VAL" | grep -vx 'localhost' | grep -v '^$' || true)
if [[ -n $NON_LOCALHOST_LIMIT ]]; then
  # Ansible prints PLAY RECAP only on a normal end of run, so an interrupted
  # run leaves none at all -- which the awk below reports as an empty host
  # list, indistinguishable from the matched-nothing case this guard exists to
  # catch. That told an operator "this run did nothing" about a converge that
  # had already written 60 policies to OpenBao.
  if ! grep -q '^PLAY RECAP' "$LOG_FILE"; then
    echo "ERROR: the run ended before Ansible printed a play recap — it was interrupted or crashed." >&2
    echo "This says NOTHING about how much work it completed first; read the log before concluding it did nothing." >&2
    [[ $STATUS -eq 0 ]] && STATUS=1
  else
    RECAP_HOSTS=$(awk '/^PLAY RECAP/{f=1;next} f && NF{print $1}' "$LOG_FILE")
    NON_LOCALHOST_RECAP=$(grep -vx 'localhost' <<<"$RECAP_HOSTS" || true)
    if [[ -z $NON_LOCALHOST_RECAP ]]; then
      echo "ERROR: --limit ($LIMIT_VAL) asked for hosts beyond localhost, but the play recap shows only localhost — this run did nothing." >&2
      echo "Check the group name against the inventory loader that actually populates it (it may live in a different repo)." >&2
      STATUS=1
    fi
  fi
fi

# site.yml isolates play failures in block/rescue, so ansible-playbook exits 0
# while the recap still reports failed= on a host. The exit code alone is not a
# converge verdict; the recap is. Applies to every run, not only a --limit one.
if grep -q '^PLAY RECAP' "$LOG_FILE"; then
  FAILED_HOSTS=$(awk '/^PLAY RECAP/{f=1;next} f && NF && (/failed=[1-9]/ || /unreachable=[1-9]/){print $1}' "$LOG_FILE")
  if [[ -n $FAILED_HOSTS ]]; then
    echo "ERROR: the play recap reports failed/unreachable hosts (ansible exited $STATUS):" >&2
    sed 's/^/  /' <<<"$FAILED_HOSTS" >&2
    STATUS=1
  fi
fi

echo "Run log: $LOG_FILE"
exit "$STATUS"
