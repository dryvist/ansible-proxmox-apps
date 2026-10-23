from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = yaml.safe_load(
    (ROOT / "roles/openproject_docker/defaults/main.yml").read_text(
        encoding="utf-8"
    )
)
DOMAIN_GROUPS = yaml.safe_load(
    (ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml").read_text(
        encoding="utf-8"
    )
)["openbao_secrets_domain_groups"]


def test_openproject_secret_comes_from_prefetched_apps_domain():
    secret = DEFAULTS["openproject_docker_secret_key_base"]
    assert "bao_apps_secrets.openproject_secret_key_base" in secret
    assert "lookup('env', 'OPENPROJECT_SECRET_KEY_BASE')" not in secret
    assert "| mandatory(" in secret
    assert "must be supplied before the role runs" in secret


def test_openproject_group_is_in_apps_prefetch_scope():
    assert "openproject_group" in DOMAIN_GROUPS["apps"]
