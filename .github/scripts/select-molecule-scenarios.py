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
  * otherwise -> every scenario that references a changed role or whose
    directory changed, plus `default`.

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
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO / "molecule"
ROLE_DIR = REPO / "roles"

# Changes here can affect any scenario, so they select all of them.
SHARED = re.compile(
    r"^(inventory/|playbooks/|requirements\.yml$|requirements-ci\.txt$"
    r"|\.github/workflows/(?:ci-gate|_molecule)\.yml$"
    r"|\.github/scripts/select-molecule-scenarios\.py$)"
)
ROLE_PATH = re.compile(r"^roles/([^/]+)/")
SCENARIO_PATH = re.compile(r"^molecule/([^/]+)/")
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


def scenarios_on_disk() -> list[str]:
    """Scenario names under molecule/.

    A molecule.yml is what makes a directory a scenario. molecule/ also holds
    shared resource directories that scenarios reference, and those resolve no
    roles at all — which is indistinguishable, to the self-check, from a
    scenario whose parsing broke. Matching the same rule the sibling selector
    in scripts/ uses keeps a new shared directory from tripping that guard.
    """
    return sorted(p.name for p in SCENARIO_DIR.iterdir() if (p / "molecule.yml").is_file())


def scenario_roles(known: set[str]) -> dict[str, set[str]]:
    """Roles each scenario exercises, closed over role-to-role references.

    The closure is iterated to a fixed point rather than bounded to one level:
    a scenario that includes role A, where A includes B, is affected by a change
    to B. Bounding the depth would silently miss exactly that case.
    """
    mapping: dict[str, set[str]] = {}
    for scenario in scenarios_on_disk():
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
        ["git", "diff", "--name-only", "-z", f"{base_sha}...HEAD"],
        capture_output=True,
        check=True,
    ).stdout
    return diff_paths(out)


def diff_paths(output: bytes) -> list[str]:
    return [os.fsdecode(path) for path in output.split(b"\0") if path]


def changed_scenarios(paths: list[str], available: set[str]) -> tuple[set[str], list[str]]:
    selected: set[str] = set()
    unrecognised: list[str] = []
    for path in paths:
        if not path.startswith("molecule/"):
            continue
        match = SCENARIO_PATH.match(path)
        if match and match.group(1) in available:
            selected.add(match.group(1))
        else:
            unrecognised.append(path)
    return selected, unrecognised


def changed_roles(paths: list[str], available: set[str]) -> tuple[set[str], set[str]]:
    selected: set[str] = set()
    unrecognised: set[str] = set()
    for path in paths:
        match = ROLE_PATH.match(path)
        if not match:
            continue
        if match.group(1) in available:
            selected.add(match.group(1))
        else:
            unrecognised.add(match.group(1))
    return selected, unrecognised


def output_line(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)[1:-1]


def summary_value(value: str) -> str:
    return escape(output_line(value))


def output_records(scenarios: list[str], reason: str) -> tuple[str, str, str]:
    payload = json.dumps(sorted(set(scenarios)))
    reason = output_line(reason)
    return payload, reason, f"list={payload}\nreason={reason}\n"


def summary_records(scenarios: list[str], reason: str) -> str:
    return (
        f"### Molecule selection\n\n<code>{summary_value(reason)}</code>\n\n"
        f"Running {len(set(scenarios))} scenario(s): "
        f"<code>{', '.join(summary_value(s) for s in sorted(set(scenarios)))}</code>\n"
    )


def emit(scenarios: list[str], reason: str) -> None:
    payload, output_reason, records = output_records(scenarios, reason)
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(records)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(summary_records(scenarios, reason))
    print(f"{output_reason}: {payload}")


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

    selected, unrecognised = changed_scenarios(
        ["molecule/immich/converge.yml"], set(mapping)
    )
    if selected != {"immich"} or unrecognised:
        failures.append("a changed scenario directory no longer selects that scenario")

    selected, unrecognised = changed_scenarios(["molecule/not-a-scenario/config.yml"], set(mapping))
    if selected or unrecognised != ["molecule/not-a-scenario/config.yml"]:
        failures.append("an unrecognised molecule path no longer widens the matrix")

    if not SHARED.match(".github/workflows/ci-gate.yml"):
        failures.append("the Molecule gate workflow no longer widens the matrix")

    selected, unrecognised = changed_roles(["roles/no-longer-present/tasks/main.yml"], known)
    if selected or unrecognised != {"no-longer-present"}:
        failures.append("an unrecognised role path no longer widens the matrix")

    control_path = "molecule/evil\n\r\x1bscenario/converge.yml"
    if diff_paths((control_path + "\0").encode()) != [control_path]:
        failures.append("NUL-delimited changed paths no longer preserve control characters")
    selected, unrecognised = changed_scenarios([control_path], set(mapping))
    if selected or unrecognised != [control_path]:
        failures.append("a control-character Molecule path no longer widens the matrix")
    _, _, records = output_records(["default"], f"unrecognised path `{control_path}`")
    if records.count("\n") != 2 or r"\n" not in records or r"\r" not in records or r"\u001b" not in records:
        failures.append("control characters no longer stay on one output line")
    malicious_summary = "evil\n### Injected <a href='https://example.invalid'>link</a>"
    safe_summary = summary_value(malicious_summary)
    if "\n" in safe_summary or "<a" in safe_summary or "&lt;a" not in safe_summary:
        failures.append("scenario names no longer stay safe in the step summary")
    malicious_reason = "molecule/x`) [attacker](https://example.invalid) (`/converge.yml </code> **bold**"
    summary = summary_records([malicious_summary], malicious_reason)
    if summary.count("\n") != 5 or "\n### Injected" in summary or "<a" in summary or summary.count("<code>") != 2 or summary.count("</code>") != 2:
        failures.append("step summary records no longer stay structurally safe")

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

    all_scenarios = scenarios_on_disk()
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

    scenario_hits, unknown_scenario_hits = changed_scenarios(changed, set(all_scenarios))
    if unknown_scenario_hits:
        emit(all_scenarios, f"full matrix: unrecognised Molecule path changed (`{unknown_scenario_hits[0]}`)")
        return 0

    known = roles_on_disk()
    touched, unknown_roles = changed_roles(changed, known)
    if unknown_roles:
        emit(all_scenarios, f"full matrix: unrecognised role changed (`{sorted(unknown_roles)[0]}`)")
        return 0
    if not touched and not scenario_hits:
        emit(["default"], "no role changed; running `default` only")
        return 0

    selected = set(scenario_hits)
    if touched:
        mapping = scenario_roles(known)
        selected |= {s for s, roles in mapping.items() if roles & touched}
    selected.add("default")
    details = []
    if touched:
        details.append(f"roles changed: `{'`, `'.join(sorted(touched))}`")
    if scenario_hits:
        details.append(f"scenarios changed: `{'`, `'.join(sorted(scenario_hits))}`")
    emit(sorted(selected), "; ".join(details))
    return 0


if __name__ == "__main__":
    sys.exit(main())
