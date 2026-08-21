#!/usr/bin/env python3
"""Pick the Molecule scenarios a change actually needs.

The mapping from role to scenario is DERIVED FROM THE TREE, never hand-listed.
A hand-listed table would be wrong the day it was written: `default` exercises
`mssql_docker` rather than a role of its own, `postgres` also exercises
`nautobot`, and `sonarr_language_audit` also exercises `sonarr`. It would then
drift every time someone added a role to a scenario and forgot the table.

Selection rules, in order:

  * not a pull request, or a pull request into the production branch -> every
    scenario. Promotion is the one place a full sweep is guaranteed, and it is
    what makes narrowing safe everywhere else.
  * a shared input changed (inventory, playbooks, requirements, this script,
    the workflow) -> every scenario, because those genuinely affect all of them.
  * otherwise -> every scenario that references a changed role, plus `default`.

A role with no scenario referencing it selects `default` alone. That is honest:
no scenario exercises it, so running the rest would test nothing about it. The
selection and its reason are written to the step summary, so a narrowed run is
visible rather than silent.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO / "molecule"
ROLE_DIR = REPO / "roles"

# Changes here can affect any scenario, so they select all of them.
SHARED = re.compile(
    r"^(inventory/|playbooks/|requirements\.yml$|requirements-ci\.txt$"
    r"|\.github/workflows/_molecule\.yml$|\.github/scripts/select-molecule-scenarios\.py$)"
)
ROLE_PATH = re.compile(r"^roles/([^/]+)/")
# `role: foo`, `- name: foo`, and the `name:` under include_role/import_role.
#
# Both guards are load-bearing and were added after this misparsed every
# include_role block: the lookbehind stops `role` matching the tail of
# `include_role`, and the horizontal-only whitespace stops the match running
# across a newline into the following key. Without them, `include_role:\n
# name: mssql_docker` captured the literal string "name" and the role was lost.
ROLE_REF = re.compile(r"""(?<![a-z_])(?:role|name)[ \t]*:[ \t]*["']?([a-z0-9_.]+)""")


def roles_on_disk() -> set[str]:
    return {p.name for p in ROLE_DIR.iterdir() if p.is_dir()} if ROLE_DIR.is_dir() else set()


def referenced_roles(paths: list[Path], known: set[str]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found |= {
            role
            for match in ROLE_REF.findall(text)
            if (role := match.rsplit(".", 1)[-1]) in known
        }
    return found


def scenario_roles(known: set[str]) -> dict[str, set[str]]:
    """Roles each scenario exercises, closed over role-to-role references.

    The closure is iterated to a fixed point rather than bounded to one level:
    a scenario that includes role A, where A includes B, is affected by a change
    to B. Bounding the depth would silently miss exactly that case.
    """
    mapping: dict[str, set[str]] = {}
    for scenario in sorted(p.name for p in SCENARIO_DIR.iterdir() if p.is_dir()):
        direct = referenced_roles(sorted((SCENARIO_DIR / scenario).glob("*.yml")), known)
        closed = set(direct)
        pending = list(direct)
        while pending:
            role = pending.pop()
            files = sorted((ROLE_DIR / role).rglob("*.yml"))
            for dep in referenced_roles(files, known) - closed:
                closed.add(dep)
                pending.append(dep)
        mapping[scenario] = closed
    return mapping


def changed_files(base_sha: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def emit(scenarios: list[str], reason: str) -> None:
    payload = json.dumps(sorted(set(scenarios)))
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"list={payload}\n")
            fh.write(f"reason={reason}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Molecule selection\n\n{reason}\n\n")
            fh.write(f"Running {len(set(scenarios))} scenario(s): "
                     f"`{'`, `'.join(sorted(set(scenarios)))}`\n")
    print(f"{reason}: {payload}")


def self_check() -> int:
    """Assert the parser still resolves roles, against the real tree.

    This exists because the reference regex silently matched the tail of
    `include_role` and captured the literal word "name", so every scenario
    resolved to nothing and the selection quietly fell back to `default` alone —
    green, fast, and testing almost nothing. The invariant that catches that
    class of failure is "no scenario resolves an empty role set".
    """
    known = roles_on_disk()
    mapping = scenario_roles(known)
    failures: list[str] = []

    empty = sorted(s for s, roles in mapping.items() if not roles)
    if empty:
        failures.append(f"scenarios resolving no roles at all: {empty}")

    # A scenario that exercises a role of another name is the case a
    # hand-written table gets wrong; assert the known cross-scenario link stays wired.
    for role, expected in (("nautobot", "postgres"),):
        hit = {s for s, roles in mapping.items() if role in roles}
        if expected not in hit:
            failures.append(f"a change to '{role}' no longer selects '{expected}' (selects {sorted(hit)})")

    for line in failures:
        print(f"FAIL: {line}", file=sys.stderr)
    if failures:
        return 1
    print(f"self-check OK: {len(mapping)} scenarios, "
          f"{sum(len(r) for r in mapping.values())} role references resolved")
    return 0


def main() -> int:
    if "--self-check" in sys.argv:
        return self_check()

    all_scenarios = sorted(p.name for p in SCENARIO_DIR.iterdir() if p.is_dir())
    event = os.environ.get("EVENT_NAME", "")
    base_ref = os.environ.get("BASE_REF", "")
    base_sha = os.environ.get("BASE_SHA", "")
    production = os.environ.get("PRODUCTION_BRANCH", "main")

    if event != "pull_request" or not base_sha:
        emit(all_scenarios, f"full matrix: event `{event or 'unknown'}` is not a pull request")
        return 0
    if base_ref == production:
        emit(all_scenarios, f"full matrix: promotion into `{production}`")
        return 0

    changed = changed_files(base_sha)
    shared_hits = [f for f in changed if SHARED.match(f)]
    if shared_hits:
        emit(all_scenarios, f"full matrix: shared input changed (`{shared_hits[0]}`)")
        return 0

    known = roles_on_disk()
    touched = {m.group(1) for f in changed if (m := ROLE_PATH.match(f))} & known
    if not touched:
        emit(["default"], "no role changed; running `default` only")
        return 0

    mapping = scenario_roles(known)
    selected = {s for s, roles in mapping.items() if roles & touched}
    selected.add("default")
    emit(sorted(selected), f"roles changed: `{'`, `'.join(sorted(touched))}`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
