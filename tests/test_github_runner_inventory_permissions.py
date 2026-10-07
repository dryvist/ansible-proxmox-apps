"""Keep the runner identity able to read its read-only topology mount."""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "roles" / "github_runner" / "tasks" / "main.yml"
FAILURE_FIXTURE = ROOT / "tests" / "fixtures" / "github_runner_inventory_permission_error.txt"


def test_inventory_copy_matches_the_runtime_runner_identity():
    """The real runner failure fixture must be covered by the role contract."""
    failure = FAILURE_FIXTURE.read_text(encoding="utf-8").strip()
    match = re.fullmatch(
        r"PermissionError: \[Errno 13\] Permission denied: '([^']+)'", failure
    )
    assert match is not None

    defaults = yaml.safe_load(
        (ROOT / "roles" / "github_runner" / "defaults" / "main.yml").read_text(
            encoding="utf-8"
        )
    )
    assert match.group(1) == defaults["github_runner_inventory_mount"]

    tasks = yaml.safe_load(TASKS_FILE.read_text(encoding="utf-8"))
    names = [task.get("name") for task in tasks]
    identity_index = names.index("Read the runner account identity from the image")
    facts_index = names.index("Set the runner UID and GID facts from the image")
    user_index = names.index("Set the Docker user fact from the image identity")
    inventory_index = names.index("Deploy the published inventory for the e2e suite")

    assert identity_index < facts_index < user_index < inventory_index
    identity_argv = tasks[identity_index]["ansible.builtin.command"]["argv"]
    assert identity_argv[-2:] == [
        "{{ github_runner_image }}",
        "{{ github_runner_container_user_name }}",
    ]
    facts = tasks[facts_index]["ansible.builtin.set_fact"]
    assert "uid=" in facts["github_runner_container_uid"]
    assert "gid=" in facts["github_runner_container_gid"]
    copy = tasks[inventory_index]["ansible.builtin.copy"]
    assert copy["owner"] == "{{ github_runner_container_uid }}"
    assert copy["group"] == "{{ github_runner_container_gid }}"
    assert copy["mode"] == "0400"
    assert tasks[inventory_index]["no_log"] is True
