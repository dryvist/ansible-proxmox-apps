"""The standby replay delay is empty by default, set for postgres_ai, and applied only on a standby by reload.

roles/postgres/tasks/main/cluster_config.yml writes max_standby_streaming_delay only when the node is a
standby and postgres_standby_max_streaming_delay is non-empty. The task's own when-clauses are rendered
here for each role and value combination, so a dropped gate fails this test rather than a live standby.
"""

from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
SETTING = "max_standby_streaming_delay"


def _load(relative: str):
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def _setting_task() -> dict:
    tasks = _load("roles/postgres/tasks/main/cluster_config.yml")[0]["block"]
    (task,) = [
        t for t in tasks if t.get("community.postgresql.postgresql_alter_system", {}).get("param") == SETTING
    ]
    return task


def _gate_passes(task: dict, **variables) -> bool:
    env = Environment()
    return all(env.compile_expression(clause)(**variables) for clause in task["when"])


def test_role_default_is_empty():
    defaults = _load("roles/postgres/defaults/main/01-replication.yml")
    assert defaults["postgres_standby_max_streaming_delay"] == ""


def test_postgres_ai_group_sets_thirty_minutes():
    group_vars = _load("inventory/group_vars/postgres_ai_group.yml")
    assert group_vars["postgres_standby_max_streaming_delay"] == "30min"


def test_setting_is_written_only_on_a_standby_with_a_value():
    task = _setting_task()
    assert _gate_passes(task, postgres_role="standby", postgres_standby_max_streaming_delay="30min")
    assert not _gate_passes(task, postgres_role="primary", postgres_standby_max_streaming_delay="30min")
    assert not _gate_passes(task, postgres_role="standby", postgres_standby_max_streaming_delay="")


def test_setting_change_reloads_and_never_restarts():
    assert _setting_task()["notify"] == "Reload postgresql"
