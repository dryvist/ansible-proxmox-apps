"""Only the Hatchet kill-test playbook may reference the hatchet-killtest OpenBao domain.

That domain mints a per-call AppRole whose token can power the Hatchet guests,
so every file that names it is listed here. Adding another reader means
editing ALLOWED_DECLARERS, which a reviewer sees.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "hatchet-killtest"
ALLOWED_DECLARERS = {"playbooks/hatchet-killtest.yml"}
SCANNED_DIRS = ("playbooks", "roles", "inventory")
SCANNED_SUFFIXES = {".yml", ".yaml", ".j2", ".json"}


def _declarers(root: Path) -> set[str]:
    found = set()
    for directory in SCANNED_DIRS:
        for path in (root / directory).rglob("*"):
            if path.suffix in SCANNED_SUFFIXES and path.is_file() and DOMAIN in path.read_text(encoding="utf-8"):
                found.add(path.relative_to(root).as_posix())
    return found


def test_only_the_kill_test_playbook_references_the_domain():
    assert _declarers(REPO_ROOT) <= ALLOWED_DECLARERS


def test_probe_sees_a_reference_outside_the_allowed_playbook(tmp_path):
    (tmp_path / "playbooks").mkdir()
    (tmp_path / "playbooks/hatchet-killtest.yml").write_text(f"- name: {DOMAIN}\n", encoding="utf-8")
    (tmp_path / "roles/other/tasks").mkdir(parents=True)
    (tmp_path / "roles/other/tasks/main.yml").write_text(f"domain: {DOMAIN}\n", encoding="utf-8")

    declarers = _declarers(tmp_path)

    assert "playbooks/hatchet-killtest.yml" in declarers
    assert "roles/other/tasks/main.yml" in declarers
    assert not declarers <= ALLOWED_DECLARERS
