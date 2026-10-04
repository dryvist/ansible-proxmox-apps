"""Render the real expressions out of the vikunja Hermes bridge task files,
never a reimplementation of them."""

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
REL = "roles/vikunja/tasks/hermes_bridge_identity_one.yml"
IDENTITIES_REL = "roles/vikunja/tasks/hermes_bridge_identities.yml"
DEFAULTS_REL = "roles/vikunja/defaults/main.yml"

BRIDGE = {
    "projects": ["read_all", "views_buckets_tasks"],
    "tasks": ["read_one", "update"],
}
TITLED_ID = 7

_USER = "{{ vikunja_hermes_identity.username }}"
RESOLVE_TASK = f"Resolve the stored token for {_USER}"
FIND_TASK = f"Find the existing titled token for {_USER}"
CURRENT_TASK = f"Record whether the stored token is current for {_USER}"
MINT_TASK = f"Mint API token for {_USER}"
PUBLISH_TASK = f"Publish the minted token to OpenBao for {_USER}"


def defaults():
    return yaml.safe_load((ROOT / DEFAULTS_REL).read_text(encoding="utf-8"))


def find(name, rel=REL):
    for task in yaml.safe_load((ROOT / rel).read_text(encoding="utf-8")):
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {rel}")


def render(expr, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template("{{ " + expr + " }}"))


def render_template(text, variables):
    """Render a set_fact value: already a full `{{ ... }}` string in the
    source, unlike a bare `when`/`failed_when` condition — do not re-wrap."""
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(text))


def all_true(conds, variables):
    if not isinstance(conds, list):
        conds = [conds]
    return all(
        c if isinstance(c, bool) else bool(render(c, variables)) for c in conds
    )


def titled(permissions, title="hermes-bridge-hermes"):
    return {"id": TITLED_ID, "title": title, "permissions": permissions}
