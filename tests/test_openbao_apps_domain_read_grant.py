"""Every path the `apps` secrets domain reads is readable by the `apps` policy.

roles/openbao_secrets reads each path of the `apps` domain with the `apps`
AppRole. A path the policy denies answers 403, and classify_reads.yml fails
the whole domain on any 403, `optional: true` included (optional only
tolerates a 404). The policy's per-app grants come from
openbao_apps_read_apps (roles/openbao/defaults/main/05c-...), rendered here
from the real expression with the real seeding maps; infrastructure/unifi is
granted directly by apps-policy.hcl.j2.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "roles" / "openbao" / "defaults" / "main"
NAMES_FILE = DEFAULTS / "05c-terrakube-and-remaining-domain-names.yml"
GENERATED_FILE = DEFAULTS / "01c-app-secrets-generated.yml"
PROMOTED_FILE = DEFAULTS / "01b-app-secrets.yml"
CRIBL_EDGE_FILE = DEFAULTS / "05h-cribl-edge-readers.yml"
DOMAINS_FILE = ROOT / "roles" / "openbao_secrets" / "defaults" / "main" / "01-domains.yml"
POLICY_TEMPLATE = ROOT / "roles" / "openbao" / "templates" / "apps-policy.hcl.j2"
MIRROR_TASKS = ROOT / "roles" / "openbao" / "tasks" / "mirror_generated_app_secrets.yml"
ROUTER_KEY_FIELDS = {
    "agy": "agy_llm_router_key",
    "recorder": "recorder_llm_router_key",
    "judge": "judge_llm_router_key",
    "hermes-private": "hermes_private_llm_router_key",
    "donna": "donna_llm_router_key",
    "zcode": "zcode_llm_router_key",
    "opencode": "opencode_llm_router_key",
}


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _read_apps(names: dict) -> set[str]:
    cribl_edge = _yaml(CRIBL_EDGE_FILE)
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "openbao_generated_app_secrets": _yaml(GENERATED_FILE)["openbao_generated_app_secrets"],
        "openbao_promoted_app_secrets": _yaml(PROMOTED_FILE)["openbao_promoted_app_secrets"],
        "openbao_apps_read_published_apps": names.get("openbao_apps_read_published_apps", []),
        "openbao_cribl_edge_mac_a_app": cribl_edge["openbao_cribl_edge_mac_a_app"],
        "openbao_cribl_edge_mac_b_app": cribl_edge["openbao_cribl_edge_mac_b_app"],
    }
    templar.available_variables["openbao_apps_read_excluded_generated_apps"] = (
        [
            templar.template(trust_as_template(app))
            for app in cribl_edge["openbao_apps_read_excluded_generated_apps"]
        ]
    )
    return set(templar.template(trust_as_template(names["openbao_apps_read_apps"])))


def _apps_domain_paths() -> list[str]:
    for domain in _yaml(DOMAINS_FILE)["openbao_secrets_domains"]:
        if domain["name"] == "apps":
            return [p["path"] if isinstance(p, dict) else p for p in domain["paths"]]
    raise AssertionError("no `apps` domain in openbao_secrets_domains")


def _unreadable(paths: list[str], read_apps: set[str], template_text: str) -> list[str]:
    missing = []
    for path in paths:
        if path.startswith("apps/") and path.split("/", 1)[1] in read_apps:
            continue
        if f"data/{path}\"" in template_text:
            continue
        missing.append(path)
    return missing


def test_every_apps_domain_path_is_granted_to_the_apps_reader():
    read_apps = _read_apps(_yaml(NAMES_FILE))
    missing = _unreadable(_apps_domain_paths(), read_apps, POLICY_TEMPLATE.read_text(encoding="utf-8"))
    assert not missing, (
        f"the `apps` domain reads {missing}, which the `apps` policy does not grant; "
        "the domain fetch fails on the 403. Add the bucket to a seeding map or to "
        "openbao_apps_read_published_apps."
    )


def test_a_published_only_bucket_is_missing_without_the_published_list():
    names = dict(_yaml(NAMES_FILE))
    names["openbao_apps_read_published_apps"] = []
    read_apps = _read_apps(names)
    missing = _unreadable(_apps_domain_paths(), read_apps, POLICY_TEMPLATE.read_text(encoding="utf-8"))
    assert "apps/pve-exporter" in missing


def test_router_consumer_keys_are_generated_and_granted_as_exact_app_paths():
    generated = _yaml(GENERATED_FILE)["openbao_generated_app_secrets"]
    for app, field in ROUTER_KEY_FIELDS.items():
        fields = generated.get(app, [])
        assert fields.count(field) == 1, f"apps/{app} must generate {field} exactly once"
        assert [name for name in fields if name.endswith("_llm_router_key")] == [field]

    read_apps = _read_apps(_yaml(NAMES_FILE))
    allowlisted_router_paths = {f"apps/{app}" for app in ROUTER_KEY_FIELDS if app in read_apps}
    assert allowlisted_router_paths == {f"apps/{app}" for app in ROUTER_KEY_FIELDS}

    policy = POLICY_TEMPLATE.read_text(encoding="utf-8")
    app_path_lines = [
        line.strip()
        for line in policy.splitlines()
        if line.lstrip().startswith("path ") and "/apps/" in line
    ]
    assert app_path_lines == [
        'path "{{ openbao_kv_mount }}/data/apps/{{ app }}" {',
        'path "{{ openbao_kv_mount }}/metadata/apps/{{ app }}" {',
    ]


def test_open_llm_router_fields_mirror_existing_generated_keys():
    generated = _yaml(GENERATED_FILE)["openbao_generated_app_secrets"]
    promoted_defaults = _yaml(PROMOTED_FILE)
    promoted = promoted_defaults["openbao_promoted_app_secrets"]["open-llm"]
    mirrors = promoted_defaults["openbao_open_llm_router_key_mirrors"]
    sources = {
        item["target_field"]: (item["source_app"], item["source_field"], item["source_variable"])
        for item in mirrors
    }
    assert sources == {
        "ZCODE_ROUTER_KEY": ("zcode", "zcode_llm_router_key", "openbao_open_llm_zcode_router_key"),
        "OPENCODE_ROUTER_KEY": (
            "opencode",
            "opencode_llm_router_key",
            "openbao_open_llm_opencode_router_key",
        ),
    }
    assert "open-llm" not in generated
    for field, (app, source_key, source_variable) in sources.items():
        assert generated[app].count(source_key) == 1
        assert promoted[field] == source_variable


def test_mirror_task_copies_the_generated_fields_without_logging_values():
    tasks = _yaml(MIRROR_TASKS)
    read_task = next(
        task for task in tasks if task["name"] == "Read the generated router-key source buckets for open-llm"
    )
    set_task = next(
        task for task in tasks if task["name"] == "Set source values for the open-llm promoted fields"
    )
    variable_expression, value_expression = next(iter(set_task["ansible.builtin.set_fact"].items()))
    assert read_task["no_log"] is True
    assert set_task["no_log"] is True

    for mirror in _yaml(PROMOTED_FILE)["openbao_open_llm_router_key_mirrors"]:
        synthetic_value = f"synthetic-{mirror['source_app']}-router-key"
        source_result = {
            "item": mirror,
            "stdout": json.dumps({"data": {"data": {mirror["source_field"]: synthetic_value}}}),
        }
        templar = Templar(loader=DataLoader())
        templar.available_variables = {"item": source_result}
        assert templar.template(trust_as_template(variable_expression)) == mirror["source_variable"]
        assert templar.template(trust_as_template(value_expression)) == synthetic_value
