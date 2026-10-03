"""Alert-path roles keep delivering when one stage or check goes away.

ntfy_docker: the Slack fan-out and the Zammad subscriber each run in their own
block/rescue, Slack first, and a final task fails the converge if either one
failed. A failing Zammad stage cannot stop Slack from deploying.

service_deadman: a host with no checks gets its earlier validator removed. If
the role just ended the host instead, the old timer would keep firing a check
that the host no longer has.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROLES = Path(__file__).resolve().parent.parent / "roles"


def _tasks(path: str) -> list[dict]:
    return yaml.safe_load((ROLES / path).read_text())


def _includes(task: dict) -> list[str]:
    return [t.get("ansible.builtin.include_tasks") for t in task.get("block", [])]


def test_ntfy_slack_stage_runs_first_and_both_stages_are_isolated():
    tasks = _tasks("ntfy_docker/tasks/main.yml")
    stages = [t for t in tasks if any(i in ("slack_fanout.yml", "zammad_subscriber.yml") for i in _includes(t))]
    assert [_includes(t) for t in stages] == [["slack_fanout.yml"], ["zammad_subscriber.yml"]]
    assert all(t.get("rescue") for t in stages), "each alert-hub stage needs its own rescue"
    final = tasks[-1]
    assert "ansible.builtin.fail" in final and "ntfy_docker_stage_failures" in final["when"]


def test_deadman_retires_the_validator_on_hosts_without_checks():
    tasks = _tasks("service_deadman/tasks/main.yml")
    assert not any("ansible.builtin.meta" in t for t in tasks), "a top-level end_host leaves an old timer firing"
    retire = tasks[0]
    assert retire["when"] == "service_deadman_checks | length == 0"
    removed = next(t for t in retire["block"] if t.get("ansible.builtin.file", {}).get("state") == "absent")
    assert any(".timer" in p for p in removed["loop"])
    assert retire["block"][-1].get("ansible.builtin.meta") == "end_host"
