"""The ai-VLAN Postgres cluster's pg_dump timers start inside the 06:00-07:00 UTC window.

group_vars/postgres_ai_group.yml sets postgres_backup_on_calendar from the
host's role (primary or standby). This renders the REAL expression for each
role and asserts both slots are in the window, distinct, and clear of the
shared cluster's slot (the postgres role default).
"""

import re
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
SLOT = re.compile(r"^\*-\*-\* 06:(\d{2}):00 UTC$")


def _group_vars() -> dict:
    return yaml.safe_load((ROOT / "inventory/group_vars/postgres_ai_group.yml").read_text(encoding="utf-8"))


def _role_default_calendar() -> str:
    defaults = yaml.safe_load(
        (ROOT / "roles/postgres/defaults/main/00-install-and-backup.yml").read_text(encoding="utf-8")
    )
    return defaults["postgres_backup_on_calendar"]


def _render(role: str) -> str:
    templar = Templar(loader=DataLoader())
    templar.available_variables = {"postgres_role": role}
    return templar.template(trust_as_template(_group_vars()["postgres_backup_on_calendar"]))


def test_each_role_starts_inside_the_window():
    for role in ("primary", "standby"):
        match = SLOT.match(_render(role))
        assert match, f"{role} calendar is not a 06:MM UTC daily slot: {_render(role)}"
        assert int(match.group(1)) < 60


def test_primary_and_standby_slots_differ_and_avoid_the_shared_cluster_slot():
    primary, standby = _render("primary"), _render("standby")
    assert primary != standby
    assert _role_default_calendar() not in (primary, standby)
