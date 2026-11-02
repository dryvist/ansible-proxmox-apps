"""Check Cribl entry-tag ownership and dynamic include propagation."""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "cribl_stream"
TAGS_FILE = ROLE / "defaults" / "main" / "05-entry-tags.yml"
TASKS_FILE = ROLE / "tasks" / "main.yml"
PLAYBOOK_FILE = ROOT / "playbooks" / "site" / "02-dns-and-pipeline.yml"
TAG_REFERENCE = re.compile(
    r"^\{\{\s*cribl_stream_entry_tags\.([a-z_]+)\s*\}\}$"
)


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
    prerequisites = data["cribl_stream_entry_prerequisites"]
    tasks = list(_tasks(yaml.safe_load(TASKS_FILE.read_text(encoding="utf-8"))))
    referenced_entries = set()

    assert set(prerequisites) == set(entry_tags)
    assert len(set(entry_tags.values())) == len(entry_tags)
    assert all(tag.startswith("cribl_stream_") for tag in entry_tags.values())

    for task in tasks:
        tags = _as_list(task.get("tags"))
        references = [
            match
            for tag in tags
            if isinstance(tag, str) and (match := TAG_REFERENCE.fullmatch(tag))
        ]
        assert len(references) == 1, task.get("name")
        entry = references[0].group(1)
        assert entry in entry_tags, task.get("name")
        referenced_entries.add(entry)

        include = _include(task)
        if include is not None:
            apply_tags = _as_list(include.get("apply", {}).get("tags"))
            apply_references = [
                match
                for tag in apply_tags
                if isinstance(tag, str) and (match := TAG_REFERENCE.fullmatch(tag))
            ]
            assert [match.group(1) for match in apply_references] == [entry]
            assert "cribl_stream" in apply_tags

    assert referenced_entries == set(entry_tags)
    assert all(
        dependency in entry_tags
        for required in prerequisites.values()
        for dependency in required
    )


def test_calling_plays_keep_the_umbrella_and_cohosted_selectors():
    plays = yaml.safe_load(PLAYBOOK_FILE.read_text(encoding="utf-8"))
    by_name = {play["name"]: _as_list(play.get("tags")) for play in plays}

    assert "cribl_stream" in by_name[
        "Configure Cribl Stream on LXC containers"
    ]
    assert "unpoller" in by_name["Install unpoller on the Cribl Stream guest"]
    assert "cribl_packs" in by_name["Install Cribl packs"]
