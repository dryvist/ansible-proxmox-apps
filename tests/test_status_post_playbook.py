"""Spec-driven status post: gate, fail-open masked reads, the tracker spec, and the status_line macro."""

from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/status-post.yml"
TEMPLATES = ROOT / "playbooks/templates"
TRACKER = ROOT / "playbooks/vars/status-posts/tracker.yml"

GREEN, YELLOW, RED = "\U0001f7e2", "\U0001f7e1", "\U0001f534"

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), extensions=["jinja2.ext.do"])


def _play():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    assert len(plays) == 1
    return plays[0]


def _line(row, value, history=()):
    macro = ENV.get_template("status-lines.j2").module.status_line
    return str(macro(row, value, list(history)))


def _message(rows, instant, history=None):
    return ENV.get_template("status-post-message.j2").render(
        status_post_rows=rows,
        status_post_title="Tracker status",
        status_post_generated_utc="2026-11-20 08:37 UTC",
        status_post_instant_reads={"results": instant},
        status_post_history_reads={"results": history or []},
    )


def _ok(value):
    return {"status": 200, "json": {"data": {"result": [{"metric": {}, "value": [0, str(value)]}]}}}


def test_the_run_stays_local_and_unprivileged():
    play = _play()
    assert play["hosts"] == "localhost"
    assert play["connection"] == "local"
    assert play["gather_facts"] is False
    assert play["become"] is False
    assert play["vars"]["ansible_become"] is False


def test_the_gate_asserts_before_any_request():
    tasks = _play()["tasks"]
    first_uri = next(index for index, task in enumerate(tasks) if "ansible.builtin.uri" in task)
    gate = tasks[0]["ansible.builtin.assert"]["that"]
    assert first_uri > 0
    assert "status_post_name is match('^[a-z0-9-]+$')" in gate
    assert "status_post_channel is match('^[A-Za-z0-9_-]+$')" in gate


def test_the_extra_var_wins_over_the_env_fallback():
    selector = _play()["vars"]["status_post_name"]
    assert selector == "{{ status_post | default(lookup('env', 'STATUS_POST'), true) }}"


def test_every_metrics_read_fails_open_and_is_masked():
    reads = [task for task in _play()["tasks"] if "ansible.builtin.uri" in task and task["ansible.builtin.uri"].get("method") == "GET"]
    assert len(reads) == 2
    for task in reads:
        assert task["failed_when"] is False
        assert task["no_log"] is True
        assert task["changed_when"] is False


def test_the_tracker_spec_has_a_title_and_a_query_on_every_row():
    spec = yaml.safe_load(TRACKER.read_text(encoding="utf-8"))
    assert spec["status_post_title"] == "Tracker status"
    assert spec["status_post_rows"]
    assert all(row.get("query") for row in spec["status_post_rows"])


@pytest.mark.parametrize(
    ("value", "mark"),
    [(50, GREEN), (49.9, YELLOW), (25, YELLOW), (24.9, RED)],
)
def test_higher_is_better_boundaries(value, mark):
    row = {"component": "lane", "label": "busy:", "green": 50, "yellow": 25, "unit": "%"}
    assert _line(row, value).startswith(mark)


@pytest.mark.parametrize(
    ("value", "mark"),
    [(500, GREEN), (500.1, YELLOW), (800, YELLOW), (801, RED)],
)
def test_lower_is_better_boundaries(value, mark):
    row = {"component": "Zammad", "label": "open tickets:", "green": 500, "yellow": 800, "higher_is_better": False}
    assert _line(row, value).startswith(mark)


def test_unmeasured_is_red():
    assert _line({"component": "Zammad", "label": "open tickets:"}, None) == f"{RED} Zammad open tickets: unmeasured"


def test_decimals_round_the_number_but_not_the_mark():
    row = {"component": "lane", "label": "busy:", "green": 50, "yellow": 25, "unit": "%", "decimals": 0}
    assert _line(row, 49.6) == f"{YELLOW} lane busy: 50%"


def test_default_formatting_is_whole_or_one_decimal():
    row = {"component": "jobs:"}
    assert _line(row, "7") == f"{GREEN} jobs: 7"
    assert _line(row, "1.234") == f"{GREEN} jobs: 1.2"


@pytest.mark.parametrize(
    ("history", "tail"),
    [
        ([[0, "1"], [1, "8"]], " ▁█ ↑7"),
        ([3, 1], " █▁ ↓2"),
        ([2, 2, 2], " ▁▁▁ →"),
    ],
)
def test_sparkline_and_arrow(history, tail):
    row = {"component": "Vikunja", "label": "open tasks:", "sparkline": True}
    assert _line(row, 8, history).endswith(tail)


def test_one_point_of_history_draws_no_sparkline():
    row = {"component": "Vikunja", "label": "open tasks:", "sparkline": True}
    assert _line(row, 8, [5]) == f"{GREEN} Vikunja open tasks: 8"


def test_a_message_with_every_read_failed_is_all_red():
    rows = yaml.safe_load(TRACKER.read_text(encoding="utf-8"))["status_post_rows"]
    lines = _message(rows, [{"status": -1} for _ in rows]).splitlines()
    assert lines[0] == "2026-11-20 08:37 UTC Tracker status"
    assert len(lines) == len(rows) + 1
    assert all(line.startswith(RED) and line.endswith("unmeasured") for line in lines[1:])


def test_a_message_renders_rows_in_spec_order_with_history():
    rows = [
        {"component": "Vikunja", "label": "open tasks:", "query": "a", "green": 4000, "yellow": 5500,
         "higher_is_better": False, "sparkline": True},
        {"component": "Zammad", "label": "open tickets:", "query": "b", "green": 500, "yellow": 800,
         "higher_is_better": False},
    ]
    ranged = [{"status": 200, "status_post_row": rows[0],
               "json": {"data": {"result": [{"values": [[0, "3900"], [1, "4100"]]}]}}}]
    lines = _message(rows, [_ok(4100), _ok(900)], ranged).splitlines()
    assert lines[1] == f"{YELLOW} Vikunja open tasks: 4100 ▁█ ↑200"
    assert lines[2] == f"{RED} Zammad open tickets: 900"
