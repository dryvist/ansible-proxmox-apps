#!/usr/bin/env python3
"""Contract checks for the native devpi-server package cache role."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles" / "devpi_server"
SHORTCUT = (
    "shortcut: no byte cap upstream; the data is a disposable pull-through cache; "
    "if the guest's disk alert fires, stop the service and clear this directory."
)


def test_devpi_server_release_and_storage_are_pinned_and_separate():
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    readme = (ROLE / "README.md").read_text()

    assert defaults["devpi_server_version"] == "6.21.0"
    assert defaults["devpi_server_port"] == 3141
    assert defaults["devpi_server_data_dir"] == "/var/lib/devpi-server"
    assert "2026-10-27" in readme
    assert SHORTCUT in readme


def test_devpi_server_unit_is_journaled_and_health_checked():
    unit = (ROLE / "templates" / "devpi-server.service.j2").read_text()
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    health = next(task for task in tasks if task["name"] == "Check devpi_server health endpoint")
    initialize = next(task for task in tasks if task["name"] == "Initialize the devpi_server data directory")
    flush_handlers = next(
        task for task in tasks
        if task.get("ansible.builtin.meta") == "flush_handlers"
    )

    assert "--restrict-modify root" in unit
    assert "StandardOutput=journal" in unit
    assert "StandardError=journal" in unit
    assert "+status" in health["ansible.builtin.uri"]["url"]
    assert initialize["no_log"] is True
    assert "--root-passwd" in initialize["ansible.builtin.command"]["argv"]
    assert tasks.index(flush_handlers) < tasks.index(health)


def test_baseline_play_targets_the_apt_cache_group():
    plays = yaml.safe_load((ROOT / "playbooks/site/01-baseline-infra.yml").read_text())
    play = next(play for play in plays if play.get("name") == "Deploy phase-1 package caches")

    assert play["hosts"] == "apt_cacher_group"
    assert play["roles"][0]["role"] == "devpi_server"
    assert play["roles"][1]["role"] == "verdaccio_cache"
    assert play["roles"][2]["role"] == "raw_cache"
    assert play["tags"] == ["package_caches"]
    assert [role["tags"] for role in play["roles"]] == [
        ["devpi_server"],
        ["verdaccio_cache"],
        ["raw_cache"],
    ]
