"""Static contracts for the localhost YouTrack play and secret pre-fetch."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SITE_PLAYBOOK = ROOT / "playbooks/site/04-secrets-and-collab-apps.yml"
PREFETCH_PLAYBOOK = ROOT / "playbooks/site/00-load-and-telemetry.yml"
SCOPE_PLAYBOOK = ROOT / "playbooks/site/00a-secrets-scope-detect.yml"


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _play(plays, name):
    return next(play for play in plays if play.get("name") == name)


def test_youtrack_settings_run_on_localhost_with_controller_apps_secrets():
    play = _play(_yaml(SITE_PLAYBOOK), "Configure YouTrack Hub settings")

    assert play["hosts"] == "localhost"
    assert play["connection"] == "local"
    assert play["become"] is False
    assert play["gather_facts"] is False
    assert {"never", "youtrack"}.issubset(play["tags"])
    assert "projects" not in play["tags"]
    assert "hostvars['localhost'].openbao_secrets_by_domain['apps']" in play[
        "vars"
    ]["bao_apps_secrets"]
    assert "bao_apps_secrets.youtrack_hub_admin_token" in play["vars"][
        "youtrack_hub_admin_token"
    ]
    assert not (ROOT / "inventory/group_vars/youtrack_group.yml").exists()

    converge = play["tasks"][0]
    assert "block" in converge and "rescue" in converge
    assert any(
        task.get("ansible.builtin.include_role", {}).get("name") == "youtrack"
        for task in converge["block"]
    )


def test_youtrack_scope_selects_localhost_and_apps_in_the_existing_prefetch():
    scope = _play(
        _yaml(SCOPE_PLAYBOOK),
        "Detect whether this run selects the YouTrack localhost consumer",
    )
    assert scope["hosts"] == "localhost"
    assert "always" in scope["tags"]
    scope_expression = scope["tasks"][0]["ansible.builtin.set_fact"][
        "openbao_secrets_youtrack_in_scope"
    ]
    assert "ansible_run_tags" in scope_expression
    assert "youtrack" in scope_expression
    assert "projects" not in scope_expression and "'all'" not in scope_expression

    prefetch = _play(
        _yaml(PREFETCH_PLAYBOOK), "Pre-fetch resource-domain secrets from OpenBao"
    )
    assert "openbao_secrets_youtrack_in_scope" in prefetch["hosts"]

    block = prefetch["tasks"][0]["block"]
    preserve_map = next(
        task
        for task in block
        if task.get("name") == "Preserve the declared OpenBao consumer map"
    )
    assert "openbao_secrets_domain_groups" in preserve_map["ansible.builtin.set_fact"][
        "openbao_secrets_domain_groups_source"
    ]

    role_task = next(
        task
        for task in block
        if task.get("name") == "Fetch each resource-domain's KV subtree via its own AppRole"
    )
    role_vars = role_task["vars"]
    assert role_task["ansible.builtin.include_role"]["name"] == (
        "dryvist.homelab.openbao_secrets"
    )
    assert "openbao_secrets_domain_groups_source" in role_vars[
        "openbao_secrets_domain_groups"
    ]
    assert "'apps': []" in role_vars["openbao_secrets_domain_groups"]
