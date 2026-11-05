#!/usr/bin/env python3
"""Install cached Ansible requirements without refreshing satisfied Galaxy pins."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import yaml
from ansible import constants as C

GIT_PINS_FILENAME = "git-collection-pins.json"


def _is_git_collection(requirement: dict) -> bool:
    return requirement.get("type") == "git"


def _write_requirements(path: Path, section: str, entries: list[dict]) -> None:
    if entries:
        path.write_text(yaml.safe_dump({section: entries}, sort_keys=False), encoding="utf-8")


def _git_pins_path() -> Path:
    # ansible-galaxy installs into the first collections path, so the pins sit
    # beside the installed collections and a cache of that directory carries them.
    return Path(C.COLLECTIONS_PATHS[0]) / GIT_PINS_FILENAME


def _load_git_pins(path: Path) -> dict[str, str]:
    try:
        pins = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(pins, dict) or not all(isinstance(ref, str) for ref in pins.values()):
        return {}
    return pins


def _git_collection_is_current(requirement: dict, pins: dict[str, str]) -> bool:
    # A git collection's pinned version is a commit SHA. The installed metadata
    # carries only the galaxy.yml version, so the recorded SHA is the only proof
    # of which revision is installed.
    version = requirement.get("version")
    return bool(version) and pins.get(requirement["name"]) == version


def _record_git_pins(path: Path, git_collections: list[dict]) -> None:
    pins = {item["name"]: item["version"] for item in git_collections if item.get("version")}
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


def _run(*args: str) -> None:
    subprocess.run(["ansible-galaxy", *args], check=True)


def main() -> None:
    requirements = yaml.safe_load(Path("requirements.yml").read_text(encoding="utf-8"))
    collections = requirements.get("collections", [])
    git_collections = [item for item in collections if _is_git_collection(item)]
    galaxy_collections = [item for item in collections if not _is_git_collection(item)]
    pins_path = _git_pins_path()
    pins = _load_git_pins(pins_path)
    stale_git = [item for item in git_collections if not _git_collection_is_current(item, pins)]
    stale_roles = [item for item in requirements.get("roles", []) if not _role_is_current(item)]

    with tempfile.TemporaryDirectory(prefix="ansible-galaxy-") as temp_dir:
        temp_path = Path(temp_dir)
        galaxy_file = temp_path / "collections.yml"
        git_file = temp_path / "git-collections.yml"
        roles_file = temp_path / "roles.yml"
        _write_requirements(galaxy_file, "collections", galaxy_collections)
        _write_requirements(git_file, "collections", stale_git)
        _write_requirements(roles_file, "roles", stale_roles)

        if galaxy_collections:
            # Default resolution skips installed versions that satisfy the pin.
            _run("collection", "install", "-r", str(galaxy_file))
        if stale_git:
            # Only collections with no recorded ref, or a different one, are reinstalled.
            _run("collection", "install", "-r", str(git_file), "--force")
        _record_git_pins(pins_path, git_collections)
        if stale_roles:
            _run("role", "install", "-r", str(roles_file), "--force")


if __name__ == "__main__":
    main()
