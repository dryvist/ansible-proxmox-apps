"""Least-privilege contract for the Hermes API key seed path."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "roles/openbao/templates/ansible-converge-policy.hcl.j2"
DATA_PATH = "{{ openbao_kv_mount }}/data/ai/hermes"
METADATA_PATH = "{{ openbao_kv_mount }}/metadata/ai/hermes"
PATH_BLOCK = re.compile(
    r'^path "(?P<path>[^"]+)" \{\n'
    r'\s+capabilities = \[(?P<capabilities>[^]]*)\]\n'
    r"\}",
    re.MULTILINE,
)


def _policy_grants() -> list[tuple[str, set[str]]]:
    policy = POLICY_PATH.read_text(encoding="utf-8")
    grants = []
    for match in PATH_BLOCK.finditer(policy):
        capabilities = {
            capability.strip().strip('"')
            for capability in match.group("capabilities").split(",")
        }
        grants.append((match.group("path"), capabilities))
    return grants


def test_ansible_converge_has_only_required_hermes_seed_capabilities():
    grants = _policy_grants()

    assert [grant for grant in grants if grant[0] == DATA_PATH] == [
        (DATA_PATH, {"read", "create", "update"})
    ]
    assert [grant for grant in grants if grant[0] == METADATA_PATH] == [
        (METADATA_PATH, {"read"})
    ]


def test_ansible_converge_has_no_hermes_wildcard_or_neighbor_grants():
    paths = {path for path, _capabilities in _policy_grants()}

    assert {path for path in paths if "/ai/hermes" in path} == {
        DATA_PATH,
        METADATA_PATH,
    }
    assert not any("/ai/" in path and "*" in path for path in paths)

    forbidden_paths = {
        "{{ openbao_kv_mount }}/data/ai/hermes/*",
        "{{ openbao_kv_mount }}/metadata/ai/hermes/*",
        "{{ openbao_kv_mount }}/data/ai/hermes-api",
        "{{ openbao_kv_mount }}/metadata/ai/hermes-api",
        "{{ openbao_kv_mount }}/data/ai/agents",
        "{{ openbao_kv_mount }}/metadata/ai/agents",
        "{{ openbao_kv_mount }}/data/ai/saas",
        "{{ openbao_kv_mount }}/metadata/ai/saas",
        "{{ openbao_kv_mount }}/delete/ai/hermes",
        "{{ openbao_kv_mount }}/destroy/ai/hermes",
        "{{ openbao_kv_mount }}/undelete/ai/hermes",
    }
    assert paths.isdisjoint(forbidden_paths)
