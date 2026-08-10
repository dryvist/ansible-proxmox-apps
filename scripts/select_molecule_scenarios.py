#!/usr/bin/env python3
"""Pick which Molecule scenarios a change actually needs.

Every Ansible-touching PR currently runs the whole scenario matrix. That is not
just slow: the test containers are siblings of the runner on a shared,
deliberately oversubscribed dockerd, so total concurrent containers is the
resource that matters, and running 20 scenarios for a one-role change is what
pushes it into starvation. Fewer scenarios per run is the direct lever.

FAIL SAFE IS THE WHOLE DESIGN. Skipping a scenario that should have run is a
silent loss of coverage — the check goes green having tested nothing, which is
strictly worse than a slow pipeline. So this narrows the matrix only when EVERY
changed path is confidently attributable to a specific scenario or is inert
(documentation). Anything unrecognised — a shared playbook, a workflow, a
requirements bump, a role no scenario is named after — returns the full set.

The mapping is deliberately by name and deliberately shallow. A scenario may
include roles beyond its namesake, and this cannot see that, which is exactly
why an unrecognised role directory widens to everything rather than narrowing to
nothing.
"""
from __future__ import annotations

import argparse
import json
import sys

# Every scenario under molecule/. Keep in step with the matrix in
# .github/workflows/_molecule.yml; verify_matrix_in_sync() checks it.
SCENARIOS = [
    "default",
    "configarr",
    "download_vpn",
    "plex",
    "radarr",
    "seerr",
    "servarr_wiring",
    "sonarr",
    "sonarr_language_audit",
    "sortarr",
    "static_site",
    "technitium_dns",
    "netmon",
    "immich",
    "openbao",
    "keepalived",
    "postgres",
    "nautobot",
    "ssh_ca_trust",
    "sqlite_backup",
]

# Scenarios whose name is not the role they exercise.
SCENARIO_ROLE_OVERRIDES = {"default": "mssql_docker"}

# Paths that cannot affect any scenario's behaviour. Kept tight on purpose:
# a path is inert only if it cannot be read at converge time.
INERT_PREFIXES = ("docs/",)
INERT_SUFFIXES = (".md",)


def role_for(scenario: str) -> str:
    """Return the role a scenario exercises."""
    return SCENARIO_ROLE_OVERRIDES.get(scenario, scenario)


def _role_to_scenarios() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for scenario in SCENARIOS:
        mapping.setdefault(role_for(scenario), []).append(scenario)
    return mapping


def select(changed_files: list[str]) -> list[str]:
    """Return the scenarios to run for these changed paths.

    Returns every scenario when any path is not confidently attributable.
    """
    role_map = _role_to_scenarios()
    selected: set[str] = set()

    for path in changed_files:
        path = path.strip()
        if not path:
            continue
        if path.startswith(INERT_PREFIXES) or path.endswith(INERT_SUFFIXES):
            continue

        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "molecule" and parts[1] in SCENARIOS:
            selected.add(parts[1])
            continue
        if len(parts) >= 3 and parts[0] == "roles" and parts[1] in role_map:
            selected.update(role_map[parts[1]])
            continue

        # Unrecognised: a shared playbook, a workflow, a requirements bump, or a
        # role no scenario is named after. Any of those can change a scenario's
        # behaviour invisibly, so widen rather than guess.
        return sorted(SCENARIOS)

    return sorted(selected)


def verify_scenarios_match_disk(molecule_dir: str) -> list[str]:
    """Return the symmetric difference between SCENARIOS and molecule/ on disk.

    This list is now the only definition of the matrix — the workflow builds it
    from here — so it has to stay true to what exists. Both directions are
    faults, in opposite ways:

    * On disk but not listed: the scenario never runs, and no PR path maps to
      it. Coverage is lost silently, which is the failure this whole selector
      exists to avoid.
    * Listed but not on disk: the matrix emits a scenario molecule cannot run,
      and the job fails on every PR that selects it.
    """
    from pathlib import Path

    on_disk = {
        child.name
        for child in Path(molecule_dir).iterdir()
        if child.is_dir() and (child / "molecule.yml").is_file()
    }
    return sorted(on_disk ^ set(SCENARIOS))


def demo() -> None:
    """Self-check. Asserts the widening cases hardest — they carry the safety."""
    # A single role narrows to its own scenario.
    assert select(["roles/nautobot/tasks/main.yml"]) == ["nautobot"]
    assert select(["molecule/seerr/converge.yml"]) == ["seerr"]

    # The renamed scenario resolves through its override, both directions.
    assert select(["roles/mssql_docker/tasks/main.yml"]) == ["default"]
    assert select(["molecule/default/converge.yml"]) == ["default"]

    # Two roles select exactly two scenarios.
    assert select(["roles/sonarr/x.yml", "roles/radarr/y.yml"]) == ["radarr", "sonarr"]

    # Documentation alone selects nothing to run.
    assert select(["docs/a.md", "README.md"]) == []

    # WIDENING — each of these must return the FULL set, because each can change
    # a scenario's behaviour without touching its directory.
    for path in (
        ".github/workflows/_molecule.yml",
        "playbooks/site.yml",
        "requirements.yml",
        "ansible.cfg",
        "roles/common/tasks/main.yml",  # real role, no scenario named for it
        "inventory/load_tofu.yml",
    ):
        assert select([path]) == sorted(SCENARIOS), f"must widen on {path}"

    # A recognised path does NOT rescue an unrecognised one in the same change.
    assert select(["roles/nautobot/tasks/main.yml", "playbooks/site.yml"]) == sorted(
        SCENARIOS
    )

    # Docs alongside a role change still narrow.
    assert select(["docs/x.md", "roles/plex/tasks/main.yml"]) == ["plex"]

    print(f"select_molecule_scenarios: OK ({len(SCENARIOS)} scenarios known)")


def main() -> int:
    """Emit the scenario list as JSON, or run the self-check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", help="newline-separated changed paths")
    parser.add_argument("--check-disk", help="path to molecule/, to verify the list")
    parser.add_argument("--demo", action="store_true", help="run the self-check")
    args = parser.parse_args()

    if args.demo:
        demo()
        return 0

    if args.check_disk:
        drift = verify_scenarios_match_disk(args.check_disk)
        if drift:
            print(
                f"SCENARIOS does not match {args.check_disk}: {drift}. A scenario on "
                "disk but unlisted never runs; a listed scenario with no directory "
                "fails the matrix.",
                file=sys.stderr,
            )
            return 1
        print(f"SCENARIOS matches {args.check_disk} ({len(SCENARIOS)} scenarios)")
        return 0

    changed = (args.changed_files or sys.stdin.read()).splitlines()
    print(json.dumps(select(changed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
