"""Static contract check for Patroni's per-cluster etcd/PKI credentials.

roles/postgres's patroni_etcd_credential.yml generates and reads back
Patroni's own etcd password at secret/etcd/<postgres_ha_scope>/rw, and
patroni_etcd_tls.yml / patroni_client_tls.yml issue this cluster's etcd
server/peer and Patroni-client certificates from OpenBao's PKI secrets
engine. All three log in as the shared ansible-converge identity -- that
token must resolve to an identity the ansible-converge policy actually
grants secret/etcd/* (KV) and pki-*-etcd/issue/* (PKI) to, or the first live
converge fails at that task -- this asserts both grants exist, the same
shape as test_donna_ai_domain_openbao_contract.py's check for ai/donna.
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


def test_ansible_converge_can_issue_from_each_cluster_pki_role():
    """Exact create/update on issue only -- no sign-verbatim, no root.

    Enumerated per openbao_pki_etcd_engines entry, never a Vault ACL glob:
    OpenBao's trailing '*' can't match a scope embedded inside one path
    segment (pki-<scope>-etcd), and '+' only ever replaces a whole segment,
    so there is no valid wildcard shorthand for a per-cluster mount name.
    """
    policy = _read("roles/openbao/templates/ansible-converge-policy.hcl.j2")

    etcd_pki_grant = (
        "{% for engine in openbao_pki_etcd_engines %}\n"
        'path "{{ engine.mount }}/issue/{{ engine.role }}" {\n'
        '  capabilities = ["create", "update"]\n}\n\n'
        'path "{{ engine.mount }}/issue/{{ engine.role }}-patroni" {\n'
        '  capabilities = ["create", "update"]\n}\n\n'
        "{% endfor %}"
    )

    assert etcd_pki_grant in policy
    # Checked as a granted capability (quoted, inside a capabilities = [...]
    # list), not a bare substring -- the surrounding comment names
    # "sign-verbatim" and "root/generate" in prose explaining what this grant
    # deliberately excludes, which a substring check would trip on.
    assert '"sign-verbatim"' not in policy
    assert '"root/generate"' not in policy
    assert "/root/generate/internal" not in policy


def test_postgres_ha_pki_placeholders_are_gone():
    """postgres_ha_pki_addr/_token never supplied an identity -- deleted.

    Every etcd/PKI task now logs in as the shared ansible-converge identity
    (postgres_ha_bao_addr/_role_id/_secret_id) instead.
    """
    for relative_path in (
        "roles/postgres/defaults/main/03-patroni.yml",
        "roles/postgres/tasks/main/patroni_prereqs.yml",
        "roles/postgres/tasks/main/patroni_etcd_tls.yml",
        "roles/postgres/tasks/main/patroni_client_tls.yml",
        "roles/postgres/tasks/main/patroni_etcd_credential.yml",
    ):
        contents = _read(relative_path)
        assert "postgres_ha_pki_addr" not in contents, relative_path
        assert "postgres_ha_pki_token" not in contents, relative_path


def test_patroni_pki_tls_tasks_log_in_and_revoke():
    """Each TLS/credential task file logs in once and revokes in an always:.

    "One login per play section, not per task" -- roles/object_storage's
    offsite/iam tasks and roles/openbao_secrets/tasks/publish.yml establish
    this shape (vault_login -> block of work -> always: vault_write revoke
    auth/token/revoke-self).
    """
    for relative_path in (
        "roles/postgres/tasks/main/patroni_etcd_tls.yml",
        "roles/postgres/tasks/main/patroni_client_tls.yml",
        "roles/postgres/tasks/main/patroni_etcd_credential.yml",
    ):
        contents = _read(relative_path)
        assert contents.count("community.hashi_vault.vault_login:") == 1, relative_path
        assert "auth/token/revoke-self" in contents, relative_path
        assert "always:" in contents, relative_path
        assert "postgres_ha_bao_addr" in contents, relative_path
