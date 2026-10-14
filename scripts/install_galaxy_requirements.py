#!/usr/bin/env python3
"""Install cached Ansible requirements without refreshing satisfied Galaxy pins."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml
from ansible import constants as C


def _is_git_collection(requirement: dict) -> bool:
    return requirement.get("type") == "git"


def _write_requirements(path: Path, section: str, entries: list[dict]) -> None:
    if entries:
        path.write_text(yaml.safe_dump({section: entries}, sort_keys=False), encoding="utf-8")


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
    stale_roles = [item for item in requirements.get("roles", []) if not _role_is_current(item)]

    with tempfile.TemporaryDirectory(prefix="ansible-galaxy-") as temp_dir:
        temp_path = Path(temp_dir)
        galaxy_file = temp_path / "collections.yml"
        git_file = temp_path / "git-collections.yml"
        roles_file = temp_path / "roles.yml"
        _write_requirements(galaxy_file, "collections", galaxy_collections)
        _write_requirements(git_file, "collections", git_collections)
        _write_requirements(roles_file, "roles", stale_roles)

        if galaxy_collections:
            # Default resolution skips installed versions that satisfy the pin.
            _run("collection", "install", "-r", str(galaxy_file))
        if git_collections:
            # Git commit pins do not match collection metadata versions.
            _run("collection", "install", "-r", str(git_file), "--force")
        if stale_roles:
            _run("role", "install", "-r", str(roles_file), "--force")


if __name__ == "__main__":
    main()
