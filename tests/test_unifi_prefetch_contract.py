"""unpoller/unifi_metrics must read the UniFi controller address from the
OpenBao prefetch fact, not a bare env lookup.

Nothing exported UNIFI_API into the Ansible run's environment under
Semaphore, so `lookup('env', 'UNIFI_API')` silently resolved empty and the
unpoller role's own assert (tasks/main.yml) failed the converge. The single
source of truth is secret/infrastructure/unifi (the same path the network
IaC repo's own Terraform provider already reads) — fetched here via
the existing openbao_secrets "apps" domain (already pulled for
cribl_stream_group, where unpoller runs) rather than a dedicated AppRole.

These render the REAL expressions out of the role defaults, never a
reimplementation, and check every wire this design decision depends on:
  - the "apps" domain declares the infrastructure/unifi path
  - the apps AppRole's policy actually grants read on that exact path
  - unifi_metrics_group is scoped into the domains this run's --limit fetches
  - the role defaults resolve from the prefetch fact ONLY: an env var of the
    same name is ignored (no hidden second source), and an empty fact fails
    loud (mandatory)
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]

FAKE_URL = "https://unifi.example.test"
FAKE_USER = "unifi-ro"
FAKE_PASS = "s3cr3t"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_role_defaults(role: str) -> dict:
    """Load role defaults, merging defaults/main/*.yml like Ansible does."""
    single = ROOT / "roles" / role / "defaults" / "main.yml"
    if single.exists():
        return yaml.safe_load(single.read_text(encoding="utf-8"))

    merged: dict = {}
    main_dir = ROOT / "roles" / role / "defaults" / "main"
    for path in sorted(main_dir.glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return merged


def _render(expr: str, variables: dict):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(expr))


def test_apps_domain_declares_the_infrastructure_unifi_path():
    defaults = _read_role_defaults("openbao_secrets")
    apps_domain = next(
        domain
        for domain in defaults["openbao_secrets_domains"]
        if domain["name"] == "apps"
    )

    assert "infrastructure/unifi" in apps_domain["paths"]


def test_apps_approle_policy_grants_read_on_infrastructure_unifi():
    policy = _read("roles/openbao/templates/apps-policy.hcl.j2")

    data_grant = (
        'path "{{ openbao_kv_mount }}/data/infrastructure/unifi" {\n'
        '  capabilities = ["read"]\n}'
    )
    metadata_grant = (
        'path "{{ openbao_kv_mount }}/metadata/infrastructure/unifi" {\n'
        '  capabilities = ["read"]\n}'
    )

    assert data_grant in policy
    assert metadata_grant in policy
    # Read-only, single path: never a wildcard grant onto the rest of the
    # infrastructure/ subtree (a comment may still mention "infrastructure/*"
    # in prose, so check the actual `path "..."` declarations, not raw text).
    path_declarations = [
        line for line in policy.splitlines() if line.startswith('path "')
    ]
    assert not any("infrastructure/*" in line for line in path_declarations)


def test_unifi_metrics_group_is_scoped_into_the_apps_domain_fetch():
    with (ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml").open() as f:
        domain_groups = yaml.safe_load(f)["openbao_secrets_domain_groups"]

    assert "unifi_metrics_group" in domain_groups["apps"]
    # unpoller runs on cribl_stream_group -- must not have regressed.
    assert "cribl_stream_group" in domain_groups["apps"]


def test_unpoller_controller_url_resolves_bao_first():
    defaults = _read_role_defaults("unpoller")
    resolved = _render(
        defaults["unpoller_controller_url"],
        {"bao_apps_secrets": {"UNIFI_API": FAKE_URL}},
    )

    assert resolved == FAKE_URL


def test_unpoller_controller_url_ignores_env_and_fails_loud_when_bao_is_empty(monkeypatch):
    monkeypatch.setenv("UNIFI_API", FAKE_URL)
    defaults = _read_role_defaults("unpoller")

    try:
        _render(defaults["unpoller_controller_url"], {"bao_apps_secrets": {}})
    except Exception:
        pass
    else:
        raise AssertionError("an env UNIFI_API must never stand in for the prefetch fact")


def test_unifi_metrics_controller_fields_ignore_env(monkeypatch):
    defaults = _read_role_defaults("unifi_metrics")
    for env_name, key in [
        ("UNIFI_API", "unifi_metrics_controller_url"),
        ("UNIFI_USERNAME", "unifi_metrics_controller_user"),
        ("UNIFI_PASSWORD", "unifi_metrics_controller_pass"),
    ]:
        monkeypatch.setenv(env_name, "from-env")
        try:
            _render(defaults[key], {"bao_apps_secrets": {}})
        except Exception:
            continue
        raise AssertionError(f"{key} must not fall back to env {env_name}")


def test_unifi_metrics_controller_fields_resolve_bao_first():
    defaults = _read_role_defaults("unifi_metrics")
    fake_bao = {
        "UNIFI_API": FAKE_URL,
        "UNIFI_USERNAME": FAKE_USER,
        "UNIFI_PASSWORD": FAKE_PASS,
    }

    assert _render(defaults["unifi_metrics_controller_url"], {"bao_apps_secrets": fake_bao}) == FAKE_URL
    assert _render(defaults["unifi_metrics_controller_user"], {"bao_apps_secrets": fake_bao}) == FAKE_USER
    assert _render(defaults["unifi_metrics_controller_pass"], {"bao_apps_secrets": fake_bao}) == FAKE_PASS
