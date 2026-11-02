"""Check Cribl entry-tag ownership and dynamic include propagation."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "cribl_stream"
TAGS_FILE = ROLE / "defaults" / "main" / "05-entry-tags.yml"
TASKS_FILE = ROLE / "tasks" / "main.yml"
BMC_TASKS_FILE = ROLE / "tasks" / "bmc_hw_metrics.yml"
PLAYBOOK_FILE = ROOT / "playbooks" / "site" / "02-dns-and-pipeline.yml"


def _as_list(value):
    return [value] if isinstance(value, str) else value or []


def _tasks(items):
    for task in items:
        yield task
        for key in ("block", "rescue", "always"):
            children = task.get(key, [])
            if isinstance(children, list):
                yield from _tasks(children)


def _include(task):
    include = task.get("ansible.builtin.include_tasks")
    if isinstance(include, str):
        return {"file": include}
    return include if isinstance(include, dict) else None


def test_main_tasks_have_one_declared_entry_tag_and_propagate_umbrella_tags():
    data = yaml.safe_load(TAGS_FILE.read_text(encoding="utf-8"))
    entry_tags = data["cribl_stream_entry_tags"]
    entry_values = set(entry_tags.values())
    compatibility_tags = set(data["cribl_stream_selector_tags"]["compatibility"])
    prerequisites = data["cribl_stream_entry_prerequisites"]
    tasks = list(_tasks(yaml.safe_load(TASKS_FILE.read_text(encoding="utf-8"))))
    used_entry_tags = set()
    literal_stream_tags = set()

    assert set(prerequisites) == set(entry_tags)
    assert len(entry_values) == len(entry_tags)
    assert all(tag.startswith("cribl_stream_") for tag in entry_values)

    for task in tasks:
        tags = _as_list(task.get("tags"))
        entry_task_tags = [tag for tag in tags if tag in entry_values]
        assert len(entry_task_tags) == 1, task.get("name")
        entry_tag = entry_task_tags[0]
        used_entry_tags.add(entry_tag)
        literal_stream_tags.update(
            tag
            for tag in tags
            if isinstance(tag, str) and tag.startswith("cribl_stream_")
        )

        include = _include(task)
        if include is not None:
            apply_tags = _as_list(include.get("apply", {}).get("tags"))
            apply_entry_tags = [tag for tag in apply_tags if tag in entry_values]
            assert apply_entry_tags == [entry_tag]
            assert "cribl_stream" in apply_tags
            literal_stream_tags.update(
                tag
                for tag in apply_tags
                if isinstance(tag, str) and tag.startswith("cribl_stream_")
            )

    assert used_entry_tags == entry_values
    assert literal_stream_tags == entry_values | {
        tag for tag in compatibility_tags if tag.startswith("cribl_stream_")
    }
    assert all(
        dependency in entry_tags
        for required in prerequisites.values()
        for dependency in required
    )


def test_bmc_provision_keeps_its_opt_in_guards_for_full_and_collector_selectors():
    tasks = list(_tasks(yaml.safe_load(BMC_TASKS_FILE.read_text(encoding="utf-8"))))
    task = next(
        task
        for task in tasks
        if task.get("name") == "Provision the Cribl read-only BMC account"
    )
    include = _include(task)

    assert include["file"] == "provision_bmc_readonly_user.yml"
    assert _as_list(task.get("tags")) == ["never", "bmc_provision"]
    assert _as_list(include.get("apply", {}).get("tags")) == ["bmc_provision"]
    when = _as_list(task.get("when"))
    assert "cribl_stream_bmc_provision_account | bool" in when
    selectors = when[-1]
    assert "'bmc_provision' in ansible_run_tags" in selectors
    assert "cribl_stream_entry_context.full | bool" in selectors
    assert "cribl_stream_entry_tags.bmc_collector in ansible_run_tags" in selectors


def test_calling_plays_keep_the_umbrella_and_cohosted_selectors():
    plays = yaml.safe_load(PLAYBOOK_FILE.read_text(encoding="utf-8"))
    by_name = {play["name"]: _as_list(play.get("tags")) for play in plays}

    assert "cribl_stream" in by_name[
        "Configure Cribl Stream on LXC containers"
    ]
    assert "unpoller" in by_name["Install unpoller on the Cribl Stream guest"]
    assert "cribl_packs" in by_name["Install Cribl packs"]
