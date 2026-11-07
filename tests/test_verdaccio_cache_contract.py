#!/usr/bin/env python3
"""Contract checks for the native Verdaccio npm cache role."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles" / "verdaccio_cache"
SHORTCUT = (
    "shortcut: no byte cap upstream; the data is a disposable pull-through cache; "
    "if the guest's disk alert fires, stop the service and clear this directory."
)


def test_verdaccio_and_node_releases_are_pinned_and_dated():
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    readme = (ROLE / "README.md").read_text()
    install = next(task for task in tasks if task["name"] == "Install pinned Verdaccio release")

    assert defaults["verdaccio_cache_version"] == "6.11.1"
    assert defaults["verdaccio_cache_node_version"] == "22.23.4"
    assert defaults["verdaccio_cache_dependency_cutoff"] == "2026-11-04T00:00:00Z"
    assert defaults["verdaccio_cache_port"] == 4873
    assert "verdaccio@{{ verdaccio_cache_version }}" in install["ansible.builtin.command"]["argv"]
    assert "--before={{ verdaccio_cache_dependency_cutoff }}" in install["ansible.builtin.command"]["argv"]
    assert "2026-10-24" in readme and "2026-10-21" in readme
    assert SHORTCUT in readme


def test_verdaccio_is_read_only_for_anonymous_clients_and_journaled():
    config = (ROLE / "templates" / "config.yaml.j2").read_text()
    unit = (ROLE / "templates" / "verdaccio-cache.service.j2").read_text()
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    health = next(task for task in tasks if task["name"] == "Check Verdaccio health endpoint")
    flush_handlers = next(
        task for task in tasks
        if task.get("ansible.builtin.meta") == "flush_handlers"
    )

    assert "max_users: -1" in config
    assert "access: $all" in config
    assert "publish: $authenticated" in config
    assert "StandardOutput=journal" in unit and "StandardError=journal" in unit
    assert "-/ping" in health["ansible.builtin.uri"]["url"]
    assert tasks.index(flush_handlers) < tasks.index(health)
