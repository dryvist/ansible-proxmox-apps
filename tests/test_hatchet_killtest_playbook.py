"""Kill test A safety contracts: derived target, unskippable restore, no token redirects."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/hatchet-killtest.yml"
TASKS = ROOT / "playbooks/tasks"
FILES = [PLAYBOOK] + sorted(TASKS.glob("hatchet_killtest_*.yml"))


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _tasks(node):
    """Every task dict, descending into block/rescue/always."""
    for task in node or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key))


def _all_tasks():
    for path in FILES:
        data = _load(path)
        plays = data if path == PLAYBOOK else [{"tasks": data}]
        for play in plays:
            yield from ((path.name, task) for task in _tasks(play.get("tasks")))


def _play():
    return _load(PLAYBOOK)[1]


def test_the_target_comes_from_the_sorted_tag_set_only():
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert "docker_ai_group" not in text
    derive = next(t for t in _play()["tasks"] if t["name"].startswith("Derive the guests"))
    assert "contains', hatchet_killtest_tag" in derive["ansible.builtin.set_fact"]["hatchet_killtest_guests"]
    assert derive["ansible.builtin.set_fact"]["hatchet_killtest_guests"].rstrip().endswith("| sort }}")


def test_caller_overrides_are_refused_before_anything_runs():
    play = _play()
    gate = play["tasks"][0]
    assert gate["name"].startswith("Refuse caller-supplied")
    guarded = set(gate["loop"])
    assert {"hatchet_killtest_target", "hatchet_killtest_vmid", "hatchet_killtest_node",
            "hatchet_killtest_api", "hatchet_killtest_guest_api", "hatchet_killtest_ca"} <= guarded
    assert guarded.isdisjoint(play["vars"])


def test_every_delegated_probe_ignores_unreachable():
    delegated = [(name, t) for name, t in _all_tasks() if "delegate_to" in t]
    assert len(delegated) >= 3
    for name, task in delegated:
        assert task.get("ignore_unreachable") is True, (name, task["name"])


def test_no_authenticated_request_follows_redirects():
    requests = [(name, t["ansible.builtin.uri"]) for name, t in _all_tasks() if "ansible.builtin.uri" in t]
    authed = [(name, uri) for name, uri in requests if "Authorization" in uri.get("headers", {})]
    assert len(authed) >= 4
    for name, uri in authed:
        assert uri["follow_redirects"] == "none", name
        assert uri["unredirected_headers"] == ["Authorization"], name


def test_restore_retries_and_always_removes_the_ca_file():
    phases = _load(TASKS / "hatchet_killtest_phases.yml")[0]
    restore = phases["always"][0]
    start = restore["block"][0]
    assert start["loop"] == [1, 2, 3]
    assert restore["rescue"], "a failed restore must be recorded, not abort the always block"
    assert [t["ansible.builtin.file"]["state"] for t in restore["always"]] == ["absent"]


def test_ready_polls_fail_fast_one_include_per_poll():
    ready = _load(TASKS / "hatchet_killtest_ready.yml")
    assert [t.get("ansible.builtin.include_tasks") for t in ready] == ["hatchet_killtest_ready_poll.yml"]
