"""Exercise the configured dispatcher sources with isolated Git and service stubs."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import urllib.request

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/agent_sandbox"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main/00-runtime.yml").read_text())
CHANGES = yaml.safe_load((ROLE / "vars/job_execution.yml").read_text())[
    "agent_sandbox_job_source_changes"
]


@pytest.fixture(scope="module")
def sources():
    result = {}
    for kind, filename in (("dispatcher", "agent-dispatch.sh"), ("entrypoint", "entrypoint.sh")):
        url = (
            "https://raw.githubusercontent.com/dryvist/nix-agent-sandbox/"
            f"{DEFAULTS['agent_sandbox_dispatch_source_commit']}/scripts/{filename}"
        )
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read()
        if kind == "dispatcher":
            pin = next(p for p in DEFAULTS["agent_sandbox_dispatch_sources"] if p["name"] == filename)
            assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
        source = raw.decode()
        result[kind + "_original"] = source
        for change in CHANGES[kind]:
            assert source.count(change["before"]) == change.get("count", 1)
            source = source.replace(change["before"], change["after"])
        checked = subprocess.run(["bash", "-n"], input=source, text=True, capture_output=True)
        assert checked.returncode == 0, checked.stderr
        result[kind] = source
    return result


def bash(script, tmp_path, **values):
    env = dict(os.environ, **values)
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=tmp_path, env=env, text=True, capture_output=True,
    )


def test_default_and_mount_contract():
    assert DEFAULTS["agent_sandbox_job_github_write"] is False
    assert DEFAULTS["agent_sandbox_opencode_context_tokens"] == 98304
    assert DEFAULTS["agent_sandbox_opencode_output_tokens"] == 8192
    profile = (ROLE / "templates/agent-dispatch-profile.sh.j2").read_text()
    assert 'agent_sandbox_job_github_write | bool | ternary("true", "false")' in profile
    assert 'agent_sandbox_job_entrypoint | quote' in profile
    assert (
        "export AGENT_OPENCODE_CONTEXT_TOKENS="
        "{{ agent_sandbox_opencode_context_tokens | int }}" in profile
    )
    assert (
        "export AGENT_OPENCODE_OUTPUT_TOKENS="
        "{{ agent_sandbox_opencode_output_tokens | int }}" in profile
    )
    patch = next(c for c in CHANGES["dispatcher"] if c["before"] == '    --name "agent-$1-$2"')
    container_args = patch["after"].splitlines()
    github_write = container_args.index('    -e "AGENT_JOB_GITHUB_WRITE=${AGENT_JOB_GITHUB_WRITE:-false}"')
    assert container_args[github_write + 1] == '    -e "AGENT_OPENCODE_CONTEXT_TOKENS=${AGENT_OPENCODE_CONTEXT_TOKENS:-}"'
    assert container_args[github_write + 2] == '    -e "AGENT_OPENCODE_OUTPUT_TOKENS=${AGENT_OPENCODE_OUTPUT_TOKENS:-}"'
    execution = yaml.safe_load((ROLE / "tasks/main/job_execution.yml").read_text())
    assert any("--network" in t.get("ansible.builtin.command", {}).get("argv", []) for t in execution)
    install = yaml.safe_load((ROLE / "tasks/main/job_source.yml").read_text())[-1]
    assert install["ansible.builtin.copy"]["validate"] == "bash -n %s"


@pytest.mark.parametrize("mode,write,permission,role", [
    ("start", "false", "read", "sandbox-opencode-read"),
    ("fix", "false", "read", "sandbox-opencode-read"),
    ("start", "true", "write", "sandbox-opencode-write"),
    ("fix", "true", "read", "sandbox-opencode-read"),
])
def test_job_credentials(sources, tmp_path, mode, write, permission, role):
    script = sources["dispatcher"].rsplit('cmd="${1:-}"', 1)[0] + r'''
job_get() {
  case "$2" in
    .tool) echo opencode-local ;;
    .repo) echo example/repository ;;
    *mode*) echo "$TEST_MODE" ;;
    *tty*) echo 0 ;;
  esac
}
service_login() { login='{"auth":{"client_token":"fixture-value","lease_duration":3600}}'; }
bao_req() {
  case "$2" in
    "$BUCKET") echo '{}' ;;
    github-agents/token)
      echo "$4" > request.json
      echo '{"data":{"token":"fixture-value"}}'
      ;;
    auth/approle/role/*/role-id) echo "$2" > role.txt; return 1 ;;
    *) return 1 ;;
  esac
}
repo_write_guard() { touch write-guard; }
scope_ok() { return 0; }
repo_guard() { :; }
gh_revoke() { :; }
abort() { :; }
mkdir -p "$STATE_DIR/job/runs/1"
run_job job 1 task
'''
    result = bash(
        script, tmp_path, TEST_MODE=mode, AGENT_JOB_GITHUB_WRITE=write,
        AGENT_DISPATCH_STATE_DIR=str(tmp_path),
        AGENT_TASK_PROFILES='{"opencode-local":{"env":[],"trackerAccess":false}}',
        BAO_ADDR="https://secrets.example.test", GIT_MIRROR_URL="https://git.example.test",
    )
    assert result.returncode == 1
    assert json.loads((tmp_path / "request.json").read_text())["permissions"]["contents"] == permission
    assert (tmp_path / "role.txt").read_text().strip() == f"auth/approle/role/{role}/role-id"
    assert (tmp_path / "write-guard").exists() is (mode == "start" and write == "true")


@pytest.mark.parametrize("mode,branch", [
    ("start", "agent/shell/fixture"),
    ("fix", "job/new"),
    ("fix", "job/existing"),
    ("fix", "ci-fix/develop/fixture"),
])
@pytest.mark.parametrize("status,history", [
    (0, "dirty"), (1, "dirty"), (0, "unchanged"), (0, "merge"),
    (0, "elsewhere"), (1, "elsewhere"),
])
def test_bundle_round_trip(sources, tmp_path, mode, branch, status, history):
    source = sources["entrypoint"]
    workspace = source[source.index('# --- Workspace'):].split('\nmake_fix_outputs()', 1)[0]
    export = source[source.index('if [ -n "${branch}" ]; then\n  if [ "${AGENT_MODE}" = start ]'):]
    export = export.split('\nif [ "${AGENT_MODE}" = fix ]; then\n  make_fix_outputs', 1)[0]
    setup = '''
git init -q -b develop remote
cd remote
git config user.name agent
git config user.email agent@example.test
echo initial > content
git add content
git commit -qm 'test(agent): initial'
if [ "$AGENT_BRANCH" = job/existing ]; then
  git checkout -qb "$AGENT_BRANCH"
  git commit --allow-empty -qm 'test(agent): existing PR'
fi
AGENT_EXPECTED_SHA=$(git rev-parse HEAD)
git clone -q --no-hardlinks . ../receiver
cd ..
workdir="$PWD"
AGENT_MODE=$TEST_MODE
AGENT_TOOL=shell
AGENT_RUN_ID=fixture
gh() { git clone --depth 50 https://github.com/example/repository repo; }
''' + workspace + '''
test "$(git symbolic-ref --short HEAD)" = "$TEST_BRANCH"
test "$(git rev-parse HEAD)" = "$AGENT_EXPECTED_SHA"
'''
    if history == "dirty":
        setup += "echo changed > content\necho added > new-file\n"
    elif history == "elsewhere":
        # Work committed on another branch: HEAD moves off base while the job
        # branch ref stays at base, leaving an empty base..branch range.
        setup += '''
git checkout -qb pushed-side
echo pushed > content
git commit -qam 'test(agent): side work'
'''
    elif history == "merge":
        setup += '''
echo job > content
git commit -qam 'test(agent): job change'
git checkout -qb side "$base"
echo side > content
git commit -qam 'test(agent): side change'
git checkout -q "$branch"
if git merge --no-ff side -m 'test(agent): merge'; then exit 1; fi
test -f .git/MERGE_HEAD
echo resolved > content
git add content
git commit -qm 'test(agent): resolve merge'
'''
    script = setup + '''
status=$TEST_STATUS
gitleaks() { return 0; }
''' + export + "\ntouch unexpected-publish\n"
    result = bash(
        script, tmp_path, TEST_MODE=mode, TEST_STATUS=str(status), AGENT_JOB_GITHUB_WRITE="false",
        AGENT_REPO="example/repository", AGENT_BRANCH=branch, TEST_BRANCH=branch,
        AGENT_GIT_NAME="agent", AGENT_GIT_EMAIL="agent@example.test",
        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"url.file://{tmp_path}/remote.insteadOf",
        GIT_CONFIG_VALUE_0="https://github.com/example/repository",
    )
    assert result.returncode == status, result.stderr
    assert not (tmp_path / "repo/unexpected-publish").exists()
    bundle = tmp_path / ".agent-result/1/branch.bundle"
    if history == "elsewhere":
        assert not bundle.exists()
        assert f"agent-entrypoint: no new commits on {branch}; no bundle" in result.stdout
        assert "Refusing to create empty bundle" not in result.stderr
        return
    assert bundle.stat().st_size > 0
    imported = bash('''
cd receiver
git bundle verify ../.agent-result/1/branch.bundle
git fetch ../.agent-result/1/branch.bundle "refs/heads/$TEST_BRANCH:refs/heads/imported"
git checkout -q imported
test "$(git rev-parse HEAD)" = "$(git -C ../repo rev-parse "$TEST_BRANCH")"
git rev-list --parents -1 HEAD
''', tmp_path, TEST_BRANCH=branch)
    assert imported.returncode == 0, imported.stderr
    expected = {"dirty": "changed\n", "unchanged": "initial\n", "merge": "resolved\n"}
    assert (tmp_path / "receiver/content").read_text() == expected[history]
    if history == "dirty":
        assert (tmp_path / "receiver/new-file").read_text() == "added\n"
    elif history == "merge":
        assert len(imported.stdout.splitlines()[-1].split()) == 3


@pytest.mark.parametrize("write", ["false", "true"])
@pytest.mark.parametrize("has_bundle", [True, False])
def test_finalize_exports_bundle_and_logs(sources, tmp_path, write, has_bundle):
    rdir = tmp_path / "job/runs/2"
    rdir.mkdir(parents=True)
    (rdir / "exit").write_text("0")
    (rdir / "cid").write_text("fixture-container")
    (rdir / "started").write_text("0")
    (tmp_path / "job/job.json").write_text('{"repo":"example/repository"}')
    (tmp_path / "branch.bundle").write_bytes(b"fixture bundle\x00\n")
    script = sources["dispatcher"].rsplit('cmd="${1:-}"', 1)[0] + r'''
job_get() { case "$2" in .mode) echo fix ;; .repo) echo example/repository ;; *) echo shell ;; esac; }
docker() {
  case "$1" in
    cp)
      [ "$2" = "fixture-container:/home/agent/work/.agent-result/2/branch.bundle" ] || return 1
      [ "$TEST_HAS_BUNDLE" = true ] || return 1
      tar -cf - branch.bundle
      ;;
    logs) echo 'fixture log' ;;
    rm) : ;;
    *) return 1 ;;
  esac
}
publish_fix() { touch published; echo succeeded > "$STATE_DIR/job/runs/2/fix_state"; }
write_result_tail() { cp "$1/log" "$1/result.txt"; }
notify() { result_lines "$1" "$2" > notified; }
finalize job 2 fixture-value
job_json job
'''
    result = bash(
        script, tmp_path, AGENT_JOB_GITHUB_WRITE=write,
        AGENT_DISPATCH_STATE_DIR=str(tmp_path), TEST_HAS_BUNDLE=str(has_bundle).lower(),
    )
    assert result.returncode == 0, result.stderr
    assert (rdir / "state").read_text().strip() == ("succeeded" if has_bundle else "failed")
    assert (rdir / "log").read_text() == "fixture log\n"
    metadata = json.loads(result.stdout)
    assert metadata["log"] == str(rdir / "log")
    if has_bundle:
        assert (rdir / "branch.bundle").read_bytes() == b"fixture bundle\x00\n"
        assert str(rdir / "branch.bundle") in (tmp_path / "notified").read_text()
        assert metadata["bundle"] == str(rdir / "branch.bundle")
    else:
        assert not (rdir / "branch.bundle").exists()
        assert "bundle: none" in (tmp_path / "notified").read_text()
        assert metadata["bundle"] == ""
    assert (tmp_path / "published").exists() is (has_bundle and write == "true")


@pytest.mark.parametrize("kind", ["dispatcher", "entrypoint"])
def test_role_configures_source_idempotently(sources, tmp_path, kind):
    destination = tmp_path / "configured-source"
    playbook = tmp_path / "verify.yml"
    original = tmp_path / "original-source"
    original.write_text(sources[kind + "_original"])
    inventory = tmp_path / "inventory.yml"
    inventory.write_text(yaml.safe_dump({"all": {"hosts": {"localhost": {
        "ansible_connection": "local", "ansible_python_interpreter": sys.executable,
    }}}}))
    playbook.write_text(yaml.safe_dump([{
        "name": "Verify job source configuration",
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "ansible_become": False,
            "job_source": {
                "path": str(destination),
                "text": "{{ lookup('file', '" + str(original) + "', rstrip=false) }}",
                "changes": CHANGES[kind],
            },
        },
        "tasks": [{
            "name": "Configure job source",
            "ansible.builtin.include_tasks": str(ROLE / "tasks/main/job_source.yml"),
        }],
    }], sort_keys=False))
    # Fixture files belong to the test runner; deployment retains root ownership.
    tasks = yaml.safe_load((ROLE / "tasks/main/job_source.yml").read_text())
    tasks[-1]["ansible.builtin.copy"]["owner"] = os.getuid()
    tasks[-1]["ansible.builtin.copy"]["group"] = os.getgid()
    fixture_tasks = tmp_path / "job-source.yml"
    fixture_tasks.write_text(yaml.safe_dump(tasks, sort_keys=False))
    playbook.write_text(playbook.read_text().replace(
        str(ROLE / "tasks/main/job_source.yml"), str(fixture_tasks)
    ))
    for changed in (1, 0):
        result = subprocess.run(
            [shutil.which("ansible-playbook"), str(playbook), "-i", str(inventory)],
            text=True, capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"changed={changed}" in result.stdout
        assert destination.read_text() == sources[kind]
