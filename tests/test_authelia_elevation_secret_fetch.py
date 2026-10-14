"""Authelia fetches its trusted elevation secret with the apps AppRole only."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PLAYBOOK = ROOT / "playbooks" / "site" / "04-secrets-and-collab-apps.yml"
PLAY_NAME = "Configure Authelia SSO portal"
PUBLISH_TASK_NAME = "Add the trusted elevation client secret to Authelia's apps secrets"


def _authelia_play() -> dict:
    with PLAYBOOK.open(encoding="utf-8") as playbook:
        plays = yaml.safe_load(playbook)
    return next(play for play in plays if play.get("name") == PLAY_NAME)


def test_authelia_fetches_elevation_secret_from_dedicated_required_path():
    play = _authelia_play()
    assert play["hosts"] == "authelia_group"
    fetch = next(
        task
        for task in play["pre_tasks"]
        if task.get("name") == "Fetch Authelia's trusted elevation client secret"
    )
    domain = fetch["vars"]["openbao_secrets_domains"][0]

    assert fetch["ansible.builtin.include_role"]["name"] == (
        "dryvist.secrets_management.openbao_secrets"
    )
    assert domain["name"] == "apps"
    assert domain["paths"] == ["core/client"]
    assert "workstation_issuer_role" not in domain
    assert fetch["when"] == "authelia_bao_elevation_enabled | default(false) | bool"


def test_fetched_secret_is_merged_only_into_authelia_apps_secrets():
    play = _authelia_play()
    publish = next(
        task
        for task in play["pre_tasks"]
        if task.get("name") == PUBLISH_TASK_NAME
    )
    expression = publish["ansible.builtin.set_fact"]["bao_apps_secrets"]

    assert "combine(" in expression
    assert "hostvars['localhost'].openbao_secrets_by_domain['apps']" in expression
    assert publish["no_log"] is True
    assert publish["when"] == "authelia_bao_elevation_enabled | default(false) | bool"
