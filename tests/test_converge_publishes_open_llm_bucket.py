"""The converge identity may write the open-llm bucket, and only that exact path."""

import re
from pathlib import Path

import jinja2
import yaml

from secrets_collection_support import SECRETS_ROLES

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = SECRETS_ROLES / "openbao" / "defaults" / "main" / "07c-base-policies.yml"
POLICY = SECRETS_ROLES / "openbao" / "templates" / "ansible-converge-policy.hcl.j2"


def _render_policy(apps: list[str]) -> str:
    env = jinja2.Environment()
    env.filters["comment"] = str  # Ansible's `comment` filter; only the header uses it
    template = env.from_string(POLICY.read_text(encoding="utf-8"))
    return template.render(
        ansible_managed="",
        openbao_kv_mount="secret",
        openbao_credential_publish_apps=apps,
        openbao_pki_etcd_engines=[],
    )


def _published_apps() -> list[str]:
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))["openbao_credential_publish_apps"]


def test_open_llm_bucket_is_published_to_with_an_exact_path_grant():
    assert "open-llm" in _published_apps()
    policy = _render_policy(_published_apps())
    assert 'path "secret/data/apps/open-llm" {\n  capabilities = ["create", "update", "read"]\n}' in policy
    assert 'path "secret/metadata/apps/open-llm" {\n  capabilities = ["read"]\n}' in policy


def test_no_wildcard_grant_on_the_apps_subtree():
    stanzas = re.findall(r'^path "([^"]+)"', _render_policy(_published_apps()), re.M)
    assert "secret/data/apps/open-llm" in stanzas
    assert [path for path in stanzas if path.startswith("secret/data/apps/") and "*" in path] == []


def test_grant_is_absent_when_the_bucket_is_not_listed():
    policy = _render_policy([app for app in _published_apps() if app != "open-llm"])
    assert "secret/data/apps/open-llm" not in policy
