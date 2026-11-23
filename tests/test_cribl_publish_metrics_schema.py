"""Publish Metrics functions use the keys Cribl's publish_metrics schema defines."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = sorted((ROOT / "roles/cribl_stream/templates/pipelines").glob("*/conf.yml.j2"))
FUNCTION = re.compile(r"^  - id: (\S+)\s*$")
METRIC_LIST = re.compile(r"^      (metrics|fields):\s*$")
ITEM_KEY = re.compile(r"^ {8}(?:- | {2})?([A-Za-z_]+):")


def _publish_metric_lists(text):
    """Return (list key, item keys) for each metric list inside a publish_metrics function."""
    lists = []
    function = None
    current = None
    for line in text.splitlines():
        match = FUNCTION.match(line)
        if match:
            function = match.group(1)
            current = None
            continue
        if function != "publish_metrics":
            continue
        match = METRIC_LIST.match(line)
        if match:
            current = (match.group(1), set())
            lists.append(current)
            continue
        if current and re.match(r"^ {6}\S", line):
            current = None
        elif current:
            item = ITEM_KEY.match(line)
            if item:
                current[1].add(item.group(1))
    return lists


def test_publish_metrics_use_the_fields_schema():
    found = 0
    for path in PIPELINES:
        for key, item_keys in _publish_metric_lists(path.read_text(encoding="utf-8")):
            found += 1
            assert key == "fields", f"{path.parent.name}: publish_metrics lists metrics under {key!r}"
            assert item_keys == {"inFieldName", "outFieldExpr", "metricType"}, (
                f"{path.parent.name}: publish_metrics field keys {sorted(item_keys)}"
            )
    assert found > 0
