#!/usr/bin/env python3
"""Install cached Ansible requirements without refreshing satisfied Galaxy pins."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from ansible import constants as C

GIT_PINS_FILENAME = "git-collection-pins.json"
# ansible-galaxy reports each installed collection as: Installing 'ns.name:ver' to '<dir>'
INSTALLED_COLLECTION = re.compile(r"^Installing '([A-Za-z0-9_]+)\.([A-Za-z0-9_]+):[^']*' to '([^']+)'", re.MULTILINE)


def _is_git_collection(requirement: dict) -> bool:
    return requirement.get("type") == "git"


def _write_requirements(path: Path, section: str, entries: list[dict]) -> None:
    if entries:
        path.write_text(yaml.safe_dump({section: entries}, sort_keys=False), encoding="utf-8")


def _load_git_pins(path: Path) -> dict[str, dict[str, str]]:
    try:
        pins = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(pins, dict):
        return {}
    for entry in pins.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("ref"), str) or not isinstance(entry.get("path"), str):
            return {}
    return pins


def _git_collection_is_current(requirement: dict, pins: dict[str, dict[str, str]], collections_root: Path) -> bool:
    # The recorded SHA says which revision was installed. The installed directory
    # says it is still there; a cache restore or manual change can remove it.
    version = requirement.get("version")
    entry = pins.get(requirement["name"])
    if not version or entry is None or entry["ref"] != version or not entry["path"]:
        return False
    return (collections_root / entry["path"]).is_dir()


def _installed_collection_path(output: str, collections_root: Path) -> str | None:
    match = INSTALLED_COLLECTION.search(output)
    if match is None:
        return None
    namespace, name, reported_dir = match.groups()
    relative = f"ansible_collections/{namespace}/{name}"
    # Record only an install that landed where the presence check will look.
    if Path(reported_dir).resolve() != (collections_root / relative).resolve():
        return None
    return relative


def _write_git_pins(path: Path, pins: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _role_is_current(requirement: dict) -> bool:
    # Role installs have no collection-style requirement check before overwrite.
    version = requirement.get("version")
    if not version or requirement.get("scm") == "git":
        return False

    for configured_path in C.DEFAULT_ROLES_PATH:
        roles_path = Path(configured_path)
        if not roles_path.is_absolute():
            roles_path = Path.cwd() / roles_path
        role_path = roles_path / requirement["name"]
        if role_path.is_dir():
            install_info = role_path / "meta" / ".galaxy_install_info"
            try:
                installed_version = yaml.safe_load(install_info.read_text(encoding="utf-8"))["version"]
            except (OSError, KeyError, TypeError, yaml.YAMLError):
                return False
            return installed_version == version
    return False


def _run(*args: str) -> str:
    result = subprocess.run(["ansible-galaxy", *args], capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    result.check_returncode()
    return result.stdout


def _install_git_collections(stale_git: list[dict], collections_root: Path) -> dict[str, dict[str, str]]:
    # One ansible-galaxy call per collection, so each reported install path belongs to one URL.
    installed: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="ansible-galaxy-git-") as temp_dir:
        for index, item in enumerate(stale_git):
            requirement_file = Path(temp_dir) / f"git-{index}.yml"
            _write_requirements(requirement_file, "collections", [item])
            # Git refs do not match installed collection metadata versions.
            output = _run("collection", "install", "-r", str(requirement_file), "--force")
            path = _installed_collection_path(output, collections_root)
            if path is None or not item.get("version"):
                # Left unrecorded, so the next run reinstalls it.
                print(f"warning: no install path reported for {item['name']}", file=sys.stderr)
                continue
            installed[item["name"]] = {"ref": item["version"], "path": path}
    return installed


def main() -> None:
    requirements = yaml.safe_load(Path("requirements.yml").read_text(encoding="utf-8"))
    collections = requirements.get("collections", [])
    git_collections = [item for item in collections if _is_git_collection(item)]
    galaxy_collections = [item for item in collections if not _is_git_collection(item)]
    collections_root = Path(C.COLLECTIONS_PATHS[0])
    pins_path = collections_root / GIT_PINS_FILENAME
    pins = _load_git_pins(pins_path)
    current_git = [item for item in git_collections if _git_collection_is_current(item, pins, collections_root)]
    current_names = {item["name"] for item in current_git}
    stale_git = [item for item in git_collections if item["name"] not in current_names]
    stale_roles = [item for item in requirements.get("roles", []) if not _role_is_current(item)]

    with tempfile.TemporaryDirectory(prefix="ansible-galaxy-") as temp_dir:
        temp_path = Path(temp_dir)
        galaxy_file = temp_path / "collections.yml"
        roles_file = temp_path / "roles.yml"
        _write_requirements(galaxy_file, "collections", galaxy_collections)
        _write_requirements(roles_file, "roles", stale_roles)

        if galaxy_collections:
            # Default resolution skips installed versions that satisfy the pin.
            _run("collection", "install", "-r", str(galaxy_file))
        installed = _install_git_collections(stale_git, collections_root)
        # Written only after every stale git install succeeded; a failure above leaves the old record.
        kept = {name: pins[name] for name in current_names}
        _write_git_pins(pins_path, {**kept, **installed})
        if stale_roles:
            _run("role", "install", "-r", str(roles_file), "--force")


if __name__ == "__main__":
    main()
