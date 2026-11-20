"""Contract tests for the tracker sql_exporter collectors and their read-only grants."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles/prometheus_stack/templates"
POSTGRES_VARS = ROOT / "inventory/group_vars/postgres_group.yml"
LOGINS = {"vikunja": "tracker_metrics_vikunja", "zammad": "tracker_metrics_zammad"}
EXPECTED = {
    "vikunja": {
        "vikunja_open_tasks": ["project"],
        "vikunja_open_tasks_by_label": ["label"],
        "vikunja_open_tasks_by_priority": ["priority"],
        "vikunja_open_tasks_by_age": ["age"],
        "vikunja_tasks_created_24h": [],
        "vikunja_tasks_done_24h": [],
    },
    "zammad": {
        "zammad_open_tickets": ["group"],
        "zammad_open_tickets_by_state": ["state"],
        "zammad_open_tickets_by_priority": ["priority"],
        "zammad_open_tickets_by_age": ["age"],
        "zammad_tickets_created_24h": [],
        "zammad_tickets_closed_24h": [],
    },
}
AGE_BUCKETS = {"lt_1d", "1d_7d", "7d_30d", "30d_90d", "gt_90d"}


def _collector(app):
    return yaml.safe_load((TEMPLATES / f"{app}.collector.yml.j2").read_text(encoding="utf-8"))


def _granted_tables(app):
    logins = yaml.safe_load(POSTGRES_VARS.read_text(encoding="utf-8"))["postgres_readonly_logins"]
    (login,) = [item for item in logins if item["name"] == LOGINS[app]]
    assert login["database"] == app
    return set(login["tables"])


def _tables(query):
    return set(re.findall(r"\b(?:FROM|JOIN)\s+([a-z_]+)", query, flags=re.IGNORECASE))


def test_each_collector_exports_the_expected_gauges_and_labels():
    for app, metrics in EXPECTED.items():
        collector = _collector(app)
        assert collector["collector_name"] == app
        found = {m["metric_name"]: m for m in collector["metrics"]}
        assert set(found) == set(metrics)
        for name, labels in metrics.items():
            metric = found[name]
            assert metric["type"] == "gauge"
            assert metric.get("key_labels", []) == labels
            assert metric["values"] == ["value"]
            for column in labels + ["value"]:
                assert re.search(rf'\bAS "?{column}"?', metric["query"]), (name, column)


def test_every_table_a_query_reads_is_granted_and_nothing_more():
    for app in EXPECTED:
        read = set().union(*(_tables(m["query"]) for m in _collector(app)["metrics"]))
        assert read == _granted_tables(app), app


def test_age_queries_emit_only_the_declared_buckets():
    for app in EXPECTED:
        (metric,) = [m for m in _collector(app)["metrics"] if m["metric_name"].endswith("_by_age")]
        assert set(re.findall(r"THEN '([a-z0-9_]+)'|ELSE '([a-z0-9_]+)'", metric["query"])) and {
            a or b for a, b in re.findall(r"THEN '([a-z0-9_]+)'|ELSE '([a-z0-9_]+)'", metric["query"])
        } == AGE_BUCKETS


def test_open_filters_exclude_closed_work():
    for metric in _collector("vikunja")["metrics"]:
        if "open" in metric["metric_name"]:
            assert "NOT t.done" in metric["query"]
    for metric in _collector("zammad")["metrics"]:
        if "open" in metric["metric_name"]:
            assert "NOT IN ('closed', 'merged', 'removed')" in metric["query"]
