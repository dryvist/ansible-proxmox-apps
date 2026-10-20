"""Shared readers for role check-mode contract tests."""

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _tasks_in(value):
    if isinstance(value, list):
        for item in value:
            yield from _tasks_in(item)
    elif isinstance(value, dict):
        if "name" in value:
            yield value
        for key in ("block", "rescue", "always"):
            if key in value:
                yield from _tasks_in(value[key])
