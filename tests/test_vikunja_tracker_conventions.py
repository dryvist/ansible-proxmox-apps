"""Tracker conventions: declared labels and kanban buckets, additive only."""

import re

from app_agent_helpers import ROOT, _render, _task_tree, _vikunja_defaults, _yaml

LABEL_TITLES = ["epic", "needs-split", "needs-info", "from-untrusted", "operator-step"]
BUCKET_TITLES = ["Backlog", "Ready", "In progress", "Blocked", "Done"]
TASK_FILES = [
    ROOT / "roles/vikunja/tasks/tracker_labels.yml",
    ROOT / "roles/vikunja/tasks/tracker_board.yml",
    ROOT / "roles/vikunja/tasks/tracker_board_one.yml",
]


def _uri_tasks(path):
    return [t for t in _task_tree(_yaml(str(path))) if "ansible.builtin.uri" in t]


def _when_text(task):
    when = task.get("when", "")
    if isinstance(when, list):
        return " ".join(str(clause) for clause in when)
    return str(when)


# --- 1: the declared labels ---------------------------------------------------


def test_the_five_label_titles_are_declared_in_order():
    labels = _vikunja_defaults()["vikunja_tracker_labels"]
    assert [row["title"] for row in labels] == LABEL_TITLES


def test_every_declared_label_has_a_hex_color_and_a_description():
    for row in _vikunja_defaults()["vikunja_tracker_labels"]:
        assert re.fullmatch(r"[0-9a-fA-F]{6}", row["hex_color"]), row
        assert len(row["description"]) > 0, row


# --- 2: the declared buckets --------------------------------------------------


def test_the_five_bucket_titles_are_declared_in_order():
    buckets = _vikunja_defaults()["vikunja_tracker_buckets"]
    assert [row["title"] for row in buckets] == BUCKET_TITLES


def test_only_ready_has_a_non_zero_limit_and_it_is_ten():
    limits = {row["title"]: row["limit"] for row in _vikunja_defaults()["vikunja_tracker_buckets"]}
    assert {title: limit for title, limit in limits.items() if limit != 0} == {"Ready": 10}


# --- 3: the declared names resolve against each other --------------------------


def test_default_done_and_rename_targets_are_declared_buckets():
    defaults = _vikunja_defaults()
    assert defaults["vikunja_tracker_default_bucket"] in BUCKET_TITLES
    assert defaults["vikunja_tracker_done_bucket"] in BUCKET_TITLES
    for new_title in defaults["vikunja_tracker_bucket_renames"].values():
        assert new_title in BUCKET_TITLES


# --- 4: the board project list renders from the agent project set ---------------


def test_board_projects_render_empty_when_the_agent_project_sets_are_undefined():
    expression = _vikunja_defaults()["vikunja_tracker_board_projects"]
    assert _render(expression, {}) == []


def test_board_projects_render_the_agent_domain_project_ids():
    expression = _vikunja_defaults()["vikunja_tracker_board_projects"]
    rendered = _render(expression, {"vikunja_agent_project_sets": {"domain": [7, 11]}})
    assert rendered == [7, 11]


# --- 5: nothing in the three files deletes -------------------------------------


def test_no_new_task_file_uses_delete_or_state_absent():
    for path in TASK_FILES:
        assert "state: absent" not in path.read_text(encoding="utf-8"), path
        for task in _uri_tasks(path):
            assert task["ansible.builtin.uri"].get("method") != "DELETE", task["name"]


# --- 6: writes are gated and never run in check mode ----------------------------


def test_every_write_request_is_gated_and_none_runs_in_check_mode():
    for path in TASK_FILES:
        for task in _uri_tasks(path):
            uri = task["ansible.builtin.uri"]
            if uri.get("method") not in ("PUT", "POST"):
                continue
            assert "when" in task, task["name"]
            if uri.get("url", "").endswith("/login"):
                # A login creates no tracker state, but the reads it feeds only
                # work in check mode if the login runs there too.
                assert task.get("check_mode") is False, task["name"]
                continue
            assert "not ansible_check_mode" in _when_text(task), task["name"]
            assert task.get("check_mode") is not False, task["name"]


# --- 7: main.yml ends with the two includes, labels first -----------------------


def test_main_ymls_last_two_tasks_are_the_convention_includes():
    tasks = list(_task_tree(_yaml("roles/vikunja/tasks/main.yml")))
    assert tasks[-2]["ansible.builtin.include_tasks"] == "tracker_labels.yml"
    assert tasks[-1]["ansible.builtin.include_tasks"] == "tracker_board.yml"
    for task in tasks[-2:]:
        assert "vikunja_tracker_conventions" in task.get("tags", []), task["name"]
