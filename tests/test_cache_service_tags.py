"""Check that each package-cache service tag selects one role."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent
PLAYBOOK = ROOT / "playbooks/site/01-baseline-infra.yml"
INVENTORY = ROOT / "tests/cache_service_tags/inventory.ini"
HEALTH_TASKS = {
    "devpi_server": "Check devpi_server health endpoint",
    "verdaccio_cache": "Check Verdaccio health endpoint",
    "raw_cache": "Check raw_cache health endpoint",
}


def _list_tasks(tag):
    result = subprocess.run(
        [
            "ansible-playbook",
            str(PLAYBOOK),
            "-i",
            str(INVENTORY),
            "--list-tasks",
            "--tags",
            tag,
        ],
        check=True,
        capture_output=True,
        cwd=ROOT,
        text=True,
    )
    return result.stdout


def test_service_tags_select_only_their_health_task():
    for tag, expected in HEALTH_TASKS.items():
        tasks = _list_tasks(tag)
        assert expected in tasks
        assert all(
            other not in tasks
            for other_tag, other in HEALTH_TASKS.items()
            if other_tag != tag
        )


def test_package_caches_tag_selects_all_three_services():
    tasks = _list_tasks("package_caches")
    assert all(task in tasks for task in HEALTH_TASKS.values())
