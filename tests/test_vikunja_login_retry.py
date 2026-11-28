"""Every tracker sign-in task waits out the per-minute sign-in limit."""

from app_agent_helpers import ROOT, _task_tree, _vikunja_defaults, _yaml

TASKS_DIR = ROOT / "roles/vikunja/tasks"


def _login_tasks():
    found = []
    for path in sorted(TASKS_DIR.glob("*.yml")):
        for task in _task_tree(_yaml(str(path))):
            uri = task.get("ansible.builtin.uri")
            if isinstance(uri, dict) and str(uri.get("url", "")).endswith("/api/v1/login"):
                found.append((path.name, task))
    return found


def test_every_login_task_retries_only_a_rate_limit_refusal():
    tasks = _login_tasks()
    assert len(tasks) >= 13
    for name, task in tasks:
        assert task.get("retries") == "{{ vikunja_login_retries }}", name
        assert task.get("delay") == "{{ vikunja_login_retry_delay }}", name
        assert task.get("until") == f"{task['register']}.status | default(0) != 429", name


def test_the_retry_window_covers_one_limit_period():
    defaults = _vikunja_defaults()
    # The tracker's limit period is 60 seconds.
    assert defaults["vikunja_login_retries"] * defaults["vikunja_login_retry_delay"] > 60
