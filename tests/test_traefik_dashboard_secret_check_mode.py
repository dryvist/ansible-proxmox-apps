"""Secret publication is skipped during Ansible check mode."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_traefik_dashboard_credential_publish_is_skipped_in_check_mode():
    tasks = yaml.safe_load((ROOT / "roles/traefik/tasks/dashboard_auth.yml").read_text())
    publish = next(
        task
        for task in tasks
        if task.get("name") == "Publish the dashboard credentials to OpenBao"
    )

    assert "not ansible_check_mode" in publish["when"]
