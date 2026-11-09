"""Only the Hatchet kill-test consumer may name the hatchet-killtest OpenBao domain.

That domain reads the token that can power the Hatchet guests,
so every file outside tests and docs that names it is listed here. Adding another
file means editing ALLOWED_DECLARERS, which a reviewer sees. The consumer must
also declare the domain as a literal one-entry list, never an expression that
loops over a wider domain catalog.
"""

from pathlib import Path
import re
import subprocess

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "hatchet-killtest"
MENTION = re.compile(rb"(?i)hatchet[-_ ]?killtest")
ALLOWED_DECLARERS = {
    "playbooks/hatchet-killtest.yml",
    "playbooks/tasks/hatchet_killtest_power.yml",
    "playbooks/tasks/hatchet_killtest_ready.yml",
    "playbooks/tasks/hatchet_killtest_ready_poll.yml",
    "playbooks/tasks/hatchet_killtest_start.yml",
    "playbooks/tasks/hatchet_killtest_phases.yml",
    "roles/hatchet_docker/README.md",
}
EXCLUDED_TOP_LEVEL = {"tests", "docs"}


def _files(root: Path):
    """Git's view (tracked plus untracked, not ignored), so .github counts and caches do not."""
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, check=False)
    if listed.returncode == 0:
        return [root / name for name in listed.stdout.decode().split("\0") if name]
    return [path for path in root.rglob("*") if ".git" not in path.relative_to(root).parts]


def _declarers(root: Path) -> set[str]:
    found = set()
    for path in _files(root):
        parts = path.relative_to(root).parts
        if not path.is_file() or parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        # Bytes, so binary files are scanned too; a read error fails the test.
        if MENTION.search(path.read_bytes()):
            found.add(path.relative_to(root).as_posix())
    return found


def _domain_lists(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "openbao_secrets_domains":
                yield value
            yield from _domain_lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _domain_lists(item)


def test_every_allowed_declarer_exists():
    assert {p for p in ALLOWED_DECLARERS if not (REPO_ROOT / p).is_file()} == set()


def test_only_the_kill_test_consumer_names_the_domain():
    assert _declarers(REPO_ROOT) <= ALLOWED_DECLARERS


def test_the_consumer_declares_only_its_own_domain_literally():
    playbook = yaml.safe_load((REPO_ROOT / "playbooks/hatchet-killtest.yml").read_text(encoding="utf-8"))
    declared = list(_domain_lists(playbook))
    assert declared, "the kill-test playbook must declare its OpenBao domain"
    for domains in declared:
        assert isinstance(domains, list), "a templated domain list can loop over the whole catalog"
        assert [d["name"] for d in domains] == [DOMAIN]
        assert domains[0]["paths"] == ["killtest/hatchet"]
        assert domains[0]["credential_domain"] == "semaphore"
        assert "workstation_issuer_role" not in domains[0]


def test_probe_sees_any_spelling_outside_the_allowed_files(tmp_path):
    (tmp_path / "playbooks").mkdir()
    (tmp_path / "playbooks/hatchet-killtest.yml").write_text(f"- name: {DOMAIN}\n", encoding="utf-8")
    for relative, text in [("roles/other/tasks/main.yml", "domain: Hatchet_KillTest\n"),
                           ("inventory/hosts.json", '{"x": "hatchet killtest"}'),
                           ("tests/fixture.yml", f"{DOMAIN}\n"),
                           ("docs/note.md", f"{DOMAIN}\n"),
                           (".github/workflows/x.yml", "run: hatchet-killtest\n"),
                           (".git/config", "hatchet-killtest\n")]:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")

    assert _declarers(tmp_path) == {
        "playbooks/hatchet-killtest.yml", "roles/other/tasks/main.yml", "inventory/hosts.json",
        ".github/workflows/x.yml"}
