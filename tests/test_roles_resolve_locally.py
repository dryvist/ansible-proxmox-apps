"""Unqualified role names resolve to roles/ here, never to a collection copy.

Importing a collection playbook (`import_playbook: <ns>.<coll>.<name>`) or
listing a collection in a play's `collections:` puts that collection ahead of
roles_path for the rest of the run. dryvist.homelab ships roles with the same
names as roles/ here, so either form would silently swap those for the
collection's copies. Collection roles are called by FQCN instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PLAYBOOKS = Path(__file__).resolve().parent.parent / "playbooks"
FQCN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$")


def _plays():
    for path in sorted(PLAYBOOKS.rglob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, list):
            for play in doc:
                if isinstance(play, dict):
                    yield path.relative_to(PLAYBOOKS), play


def offenders(plays) -> list[str]:
    found = []
    for rel, play in plays:
        target = play.get("import_playbook") or play.get("ansible.builtin.import_playbook")
        if isinstance(target, str) and FQCN.match(target):
            found.append(f"{rel}: import_playbook {target}")
        if play.get("collections"):
            found.append(f"{rel}: collections {play['collections']}")
    return found


def test_no_play_makes_a_collection_the_default():
    assert offenders(_plays()) == []


def test_a_collection_playbook_import_is_caught():
    assert offenders([(Path("x.yml"), {"import_playbook": "dryvist.homelab.converge_gate"})])
    assert offenders([(Path("x.yml"), {"hosts": "all", "collections": ["dryvist.homelab"]})])
    assert not offenders([(Path("x.yml"), {"import_playbook": "site/budget-gate.yml"})])
