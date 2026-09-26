"""Static contract check for Patroni's per-cluster etcd credential in OpenBao.

roles/postgres's patroni_etcd_credential.yml generates and reads back
Patroni's own etcd password at secret/etcd/<postgres_ha_scope>/rw over
postgres_ha_pki_token. That token must resolve to an identity the
ansible-converge policy actually grants secret/etcd/* to, or the first live
converge fails at that task -- this asserts the grant exists, the same shape
as test_donna_ai_domain_openbao_contract.py's check for ai/donna.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DATA_PATH = 'path "{{ openbao_kv_mount }}/data/etcd/*"'
CANONICAL_METADATA_PATH = 'path "{{ openbao_kv_mount }}/metadata/etcd/*"'


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_ansible_converge_owns_the_etcd_credential_wildcard():
    policy = _read("roles/openbao/templates/ansible-converge-policy.hcl.j2")

    data_grant = (
        f'{CANONICAL_DATA_PATH} {{\n'
        '  capabilities = ["create", "update", "read"]\n}'
    )
    metadata_grant = (
        f'{CANONICAL_METADATA_PATH} {{\n'
        '  capabilities = ["read", "list"]\n}'
    )

    assert data_grant in policy
    assert metadata_grant in policy


def test_patroni_etcd_credential_task_uses_the_documented_scope_path():
    task_file = _read("roles/postgres/tasks/main/patroni_etcd_credential.yml")

    assert "secret/data/etcd/{{ postgres_ha_scope }}/rw" in task_file
