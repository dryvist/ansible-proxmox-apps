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


def test_with_decimals_a_change_that_rounds_away_is_flat():
    row = {"component": "lane", "label": "tokens:", "unit": "%", "decimals": 0, "sparkline": True}
    assert _line(row, 0.3, [0.2, 0.3]).endswith(" →")


def test_a_percent_sparkline_scales_from_0_to_100():
    row = {"component": "lane", "label": "tokens:", "unit": "%", "decimals": 0, "sparkline": True}
    assert _line(row, 0.2, [0.0, 0.4, 0.1, 0.3, 0.2]) == f"{GREEN} lane tokens: 0% ▁▁▁▁▁ →"
    assert _line(row, 100, [0, 50, 100]).endswith(" ▁▅█ ↑50")


def test_a_sparkline_without_a_percent_unit_scales_min_to_max():
    row = {"component": "lane", "label": "tok/s:", "sparkline": True}
    assert _line(row, 0.4, [0.0, 0.4, 0.2]).endswith(" ▁█▅ ↓0.2")


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


def _series(lane, value):
    return {"metric": {"accelerator": lane}, "value": [0, str(value)]}


def test_a_by_row_prints_one_sorted_line_per_series_with_its_own_history():
    row = {"component": "lanes", "label": "tokens, 4 h:", "query": "q", "by": "accelerator", "unit": "%",
           "decimals": 0, "green": 90, "yellow": 45, "sparkline": True}
    instant = {"status": 200, "json": {"data": {"result": [_series("lane-b", 95), _series("lane-a", 49.6)]}}}
    ranged = [{"status": 200, "status_post_row": row, "json": {"data": {"result": [
        {"metric": {"accelerator": "lane-a"}, "values": [[0, "40"], [1, "50"]]},
        {"metric": {"accelerator": "lane-b"}, "values": [[0, "99"], [1, "95"]]},
    ]}}}]
    lines = _message([row], [instant], ranged).splitlines()
    assert lines[1:] == [
        f"{YELLOW} lane-a tokens, 4 h: 50% ▄▅ ↑10",
        f"{GREEN} lane-b tokens, 4 h: 95% ██ ↓4",
    ]


def test_a_by_row_with_no_series_is_one_unmeasured_line():
    row = {"component": "lanes", "label": "slot duty, 4 h:", "query": "q", "by": "accelerator"}
    empty = {"status": 200, "json": {"data": {"result": []}}}
    assert _message([row], [empty]).splitlines()[1:] == [f"{RED} lanes slot duty, 4 h: unmeasured"]


def test_the_gpu_spec_expands_every_row_by_accelerator():
    spec = yaml.safe_load((ROOT / "playbooks/vars/status-posts/gpu.yml").read_text(encoding="utf-8"))
    assert spec["status_post_title"] == "Local LLM utilization, 24 h"
    assert spec["status_post_rows"]
    assert all(row.get("query") and row.get("by") == "accelerator" for row in spec["status_post_rows"])


def test_the_gpu_spec_has_no_generation_rate_row():
    spec = yaml.safe_load((ROOT / "playbooks/vars/status-posts/gpu.yml").read_text(encoding="utf-8"))
    assert not [row for row in spec["status_post_rows"] if "tok/s" in row["label"]]
    assert all(row.get("green") is not None and row.get("yellow") is not None for row in spec["status_post_rows"])


def test_a_row_with_a_dashboard_uid_links_it_after_the_arrow():
    macro = ENV.get_template("status-lines.j2").module.status_line
    row = {"component": "lane", "label": "tokens:", "unit": "%", "decimals": 0, "sparkline": True, "dashboard": "abc"}
    line = str(macro(row, 100, [0, 50, 100], "https://grafana.example.test"))
    assert line.endswith(" ▁▅█ ↑50 <https://grafana.example.test/d/abc|dashboard>")


def test_no_link_without_a_dashboard_uid_or_a_base():
    macro = ENV.get_template("status-lines.j2").module.status_line
    row = {"component": "Vikunja", "label": "open tasks:"}
    assert str(macro(row, 8, [], "https://grafana.example.test")) == f"{GREEN} Vikunja open tasks: 8"
    assert str(macro(dict(row, dashboard="abc"), 8, [], "")) == f"{GREEN} Vikunja open tasks: 8"


def test_the_message_passes_the_dashboard_base_to_every_row():
    text = ENV.get_template("status-post-message.j2").render(
        status_post_rows=[{"component": "lane", "label": "busy:", "dashboard": "abc"}],
        status_post_title="t",
        status_post_generated_utc="u",
        status_post_instant_reads={"results": [_ok(5)]},
        status_post_history_reads={"results": []},
        status_post_dashboard_base="https://grafana.example.test",
    )
    assert "<https://grafana.example.test/d/abc|dashboard>" in text


def test_the_gpu_rows_link_the_local_llm_scoreboard():
    spec = yaml.safe_load((ROOT / "playbooks/vars/status-posts/gpu.yml").read_text(encoding="utf-8"))
    assert all(row.get("dashboard") == "local-llm-scoreboard" for row in spec["status_post_rows"])


def test_the_dashboard_base_is_the_grafana_vhost_from_the_environment():
    assert _play()["vars"]["status_post_dashboard_base"] == "https://grafana.{{ status_post_ingress_domain }}"


def test_the_daily_post_reads_a_24_hour_window():
    # The post runs once a day, so each figure and sparkline covers the whole day.
    spec = yaml.safe_load((ROOT / "playbooks/vars/status-posts/gpu.yml").read_text(encoding="utf-8"))
    assert all("[24h]" in row["query"] and "24 h" in row["label"] for row in spec["status_post_rows"])
    assert "timestamp() - 86400" in (ROOT / "playbooks/status-post.yml").read_text(encoding="utf-8")


def test_the_sparkline_draws_every_point_of_the_range_read():
    # The range read alone sets the window; the macro must not drop its oldest points.
    row = {"component": "lane", "label": "tokens:", "unit": "%", "decimals": 0, "sparkline": True}
    history = [[i, str(i * 4)] for i in range(13)]
    bars = _line(row, 48, history).split(" ")[-2]
    assert len(bars) == 13
    assert "step=7200" in (ROOT / "playbooks/status-post.yml").read_text(encoding="utf-8")
