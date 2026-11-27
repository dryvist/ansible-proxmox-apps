"""Prove the object-store repair run survives an unresolved inventory download.

The published inventory is served from the object store itself, so the store's
own repair play must run even when that download fails. Both directions are
exercised here against the real loader: a run scoped anywhere else still fails
hard, and a run limited to object_storage_group proceeds on the Nautobot
fallback with one logged warning.
"""

from pathlib import Path
import os
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOADER = ROOT / "inventory/load_tofu.yml"
INVENTORY = ROOT / "tests/object_storage_repair_run/inventory.yml"
FALLBACK_WARN = "WARN -- published inventory did not resolve, using the Nautobot fallback"
UNRESOLVED_FAIL = "Fail when no inventory source resolves"
LOADER_DOWNSTREAM = "Add LXC containers to inventory"

# With every environment source unset the shared role's download fails
# deterministically, which is exactly the store-down repair scenario.
_SOURCE_ENV = ("BAO_ADDR", "BAO_TOKEN", "TOFU_INVENTORY_PATH", "TOFU_INVENTORY_S3_URI")


def _run_loader(limit):
    env = {k: v for k, v in os.environ.items() if k not in _SOURCE_ENV}
    return subprocess.run(
        [
            "ansible-playbook",
            str(LOADER),
            "-i",
            str(INVENTORY),
            "--limit",
            limit,
        ],
        check=False,
        capture_output=True,
        cwd=ROOT,
        env=env,
        text=True,
        timeout=300,
    )


def test_run_scoped_elsewhere_still_fails_when_resolution_fails():
    result = _run_loader("localhost")
    assert result.returncode != 0, result.stdout
    assert UNRESOLVED_FAIL in result.stdout
    assert "fatal: [localhost]" in result.stdout
    assert FALLBACK_WARN not in result.stdout


def test_object_store_repair_run_proceeds_on_the_nautobot_fallback():
    result = _run_loader("object_storage_group,localhost")
    assert result.returncode == 0, result.stdout + result.stderr
    assert FALLBACK_WARN in result.stdout
    assert "fatal:" not in result.stdout
    # end_host in validate.yml removes localhost from the loader play in one
    # place, so every downstream loader include is skipped without carrying
    # its own tofu_data guard.
    assert LOADER_DOWNSTREAM not in result.stdout


def test_repair_run_guards_skip_without_tofu_data():
    telemetry = yaml.safe_load(
        (ROOT / "playbooks/site/00-load-and-telemetry.yml").read_text()
    )
    stats_play = next(
        play
        for play in telemetry
        if any("ansible.builtin.set_stats" in task for task in play.get("tasks", []))
    )
    assert any(
        task.get("when") == "tofu_data is defined"
        for task in stats_play["tasks"]
        if "ansible.builtin.set_stats" in task
    )

    iam = yaml.safe_load((ROOT / "roles/object_storage/tasks/iam.yml").read_text())
    ready = iam[0]["ansible.builtin.set_fact"]["object_storage_iam_ready"]
    assert "tofu_data is defined" in ready
    assert any(
        task.get("ansible.builtin.debug", {}).get("msg", "").startswith(
            "The published inventory did not resolve"
        )
        for task in iam
    )
