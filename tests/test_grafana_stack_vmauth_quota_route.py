"""vmauth gives a reader one instant query, a writer one import path, and refuses everything else."""

import json
from pathlib import Path

import jinja2
from jinja2 import meta
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/grafana_stack"
QUERY = '{__name__=~"agent_quota_.*"}'
SAMPLE_TOKEN = "fixture-quota-reader-token"
SAMPLE_WRITE_TOKEN = "fixture-quota-writer-token"
HOST_CONFIG = "/opt/grafana-stack/vmauth.yml"
CONTAINER_CONFIG = "/etc/vmauth/config.yml"
VMAUTH_TOKEN_TASKS = yaml.safe_load((ROLE / "tasks/vmauth_token.yml").read_text(encoding="utf-8"))


def _defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _token_task(name):
    return next(task for task in VMAUTH_TOKEN_TASKS if task.get("name") == name)


def _render(template_name, context):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    environment.filters["to_json"] = json.dumps
    source = (ROLE / "templates" / template_name).read_text(encoding="utf-8")
    names = {name: "fixture" for name in meta.find_undeclared_variables(environment.parse(source))}
    names.update(context)
    return environment.from_string(source).render(names)


def _compose(enabled):
    context = dict(
        grafana_stack_vm_stream_aggr_config_host_path="/opt/grafana-stack/stream-aggregation.yml",
        grafana_stack_vm_stream_aggr_config_container_path="/etc/stream-aggregation.yml",
        grafana_stack_vm_extra_flags=[],
        grafana_stack_provisioning_subdirs=[],
        grafana_stack_allow_embedding=False,
        grafana_stack_litellm_prices_enabled=False,
        grafana_stack_clickhouse_enabled=False,
        grafana_stack_vmauth_enabled=enabled,
        grafana_stack_vmauth_config_host_path=HOST_CONFIG,
        grafana_stack_vmauth_config_container_path=CONTAINER_CONFIG,
    )
    return yaml.safe_load(_render("docker-compose.yml.j2", context))


def test_quota_expression_is_the_one_allowed_selector():
    assert _defaults()["grafana_stack_vmauth_quota_expr"] == QUERY


def test_quota_tokens_are_read_from_the_agent_quota_bucket_only_when_enabled():
    defaults = _defaults()
    assert defaults["grafana_stack_vmauth_enabled"] is False
    assert defaults["grafana_stack_vmauth_quota_token"] == ""
    assert defaults["grafana_stack_vmauth_write_token"] == ""
    assert defaults["grafana_stack_vmauth_writer_label"] == "agent-quota-mac"
    read = _token_task("Read the vmauth quota tokens from OpenBao")
    request = read["community.hashi_vault.vault_kv2_get"]
    assert request == {
        "url": "{{ lookup('env', 'BAO_ADDR') | regex_replace('/+$', '') }}",
        "auth_method": "token",
        "token": "{{ lookup('env', 'BAO_TOKEN') }}",
        "engine_mount_point": "secret",
        "path": "apps/agent-quota",
        "ca_cert": "{{ openbao_ca_path }}",
        "proxies": {"http": "", "https": ""},
    }
    assert read["failed_when"] is False
    assert read["delegate_to"] == "localhost"
    assert read["check_mode"] is False
    assert read["changed_when"] is False
    assert read["no_log"] is True
    absent = _token_task("Reject vmauth quota secret read errors other than an absent bucket")
    assert absent["ansible.builtin.assert"]["that"] == [
        "grafana_stack_vmauth_secret.msg is not defined or "
        "grafana_stack_vmauth_secret.msg is search('^Invalid or missing path')"
    ]
    assert absent["no_log"] is True
    resolve = _token_task("Resolve the vmauth quota reader and writer tokens")
    assert set(resolve["ansible.builtin.set_fact"]) == {
        "grafana_stack_vmauth_quota_token",
        "grafana_stack_vmauth_write_token",
    }
    assert resolve["no_log"] is True
    assert _token_task("Require the vmauth quota reader token")["ansible.builtin.assert"]["fail_msg"] == (
        "OpenBao bucket apps/agent-quota is missing field agent_quota_reader_token"
    )
    assert _token_task("Require the vmauth quota writer token")["ansible.builtin.assert"]["fail_msg"] == (
        "OpenBao bucket apps/agent-quota is missing field agent_quota_write_token"
    )
    for task in VMAUTH_TOKEN_TASKS:
        assert task["when"] == "grafana_stack_vmauth_enabled | bool"


@pytest.mark.parametrize(
    "response, reader_ok, writer_ok",
    [
        (
            {
                "msg": "Invalid or missing path ['apps/agent-quota'] with secret version "
                "'latest'. Check the path or secret version."
            },
            False,
            False,
        ),
        ({"secret": {}}, False, False),
        (
            {"secret": {"agent_quota_reader_token": "", "agent_quota_write_token": SAMPLE_WRITE_TOKEN}},
            False,
            True,
        ),
        (
            {"secret": {"agent_quota_reader_token": SAMPLE_TOKEN, "agent_quota_write_token": "  "}},
            True,
            False,
        ),
        (
            {"secret": {"agent_quota_reader_token": SAMPLE_TOKEN, "agent_quota_write_token": SAMPLE_WRITE_TOKEN}},
            True,
            True,
        ),
    ],
)
def test_each_quota_token_is_resolved_from_its_own_field(response, reader_ok, writer_ok):
    templar = Templar(loader=DataLoader(), variables={"grafana_stack_vmauth_secret": response})
    expressions = _token_task("Resolve the vmauth quota reader and writer tokens")["ansible.builtin.set_fact"]
    tokens = {name: templar.template(trust_as_template(expression)) for name, expression in expressions.items()}
    templar.available_variables = tokens
    for assert_name, expected in (
        ("Require the vmauth quota reader token", reader_ok),
        ("Require the vmauth quota writer token", writer_ok),
    ):
        assertion = _token_task(assert_name)["ansible.builtin.assert"]
        assert templar.evaluate_conditional(trust_as_template(assertion["that"][0])) is expected
    if reader_ok:
        assert tokens["grafana_stack_vmauth_quota_token"] == SAMPLE_TOKEN
    if writer_ok:
        assert tokens["grafana_stack_vmauth_write_token"] == SAMPLE_WRITE_TOKEN


@pytest.mark.parametrize(
    "result, accepted",
    [
        ({"msg": "Invalid or missing path ['apps/agent-quota']"}, True),
        ({"msg": "Forbidden: Permission Denied to path ['apps/agent-quota']."}, False),
        ({"msg": "connection refused"}, False),
        ({"msg": "Internal Server Error"}, False),
        ({"secret": {"agent_quota_reader_token": SAMPLE_TOKEN}}, True),
    ],
)
def test_only_an_absent_quota_bucket_is_accepted_as_a_read_error(result, accepted):
    templar = Templar(loader=DataLoader(), variables={"grafana_stack_vmauth_secret": result})
    assertion = _token_task(
        "Reject vmauth quota secret read errors other than an absent bucket"
    )["ansible.builtin.assert"]
    assert templar.evaluate_conditional(trust_as_template(assertion["that"][0])) is accepted


def test_deploy_reads_the_quota_tokens_before_the_config_renders():
    deploy = yaml.safe_load((ROLE / "tasks/deploy.yml").read_text(encoding="utf-8"))
    read_index = next(
        index for index, task in enumerate(deploy)
        if task.get("ansible.builtin.import_tasks") == "vmauth_token.yml"
    )
    render_index = next(
        index for index, task in enumerate(deploy)
        if task.get("name") == "Render the vmauth quota-route config"
    )
    assert read_index < render_index


def test_vmauth_config_has_two_users_one_query_route_and_one_writer_route():
    defaults = _defaults()
    rendered = yaml.safe_load(_render("vmauth.yml.j2", {
        "grafana_stack_vmauth_quota_token": SAMPLE_TOKEN,
        "grafana_stack_vmauth_write_token": SAMPLE_WRITE_TOKEN,
        "grafana_stack_vmauth_quota_expr": defaults["grafana_stack_vmauth_quota_expr"],
        "grafana_stack_vmauth_writer_label": defaults["grafana_stack_vmauth_writer_label"],
        "grafana_stack_vm_port": 8428,
    }))
    assert list(rendered) == ["users"]
    assert len(rendered["users"]) == 2
    reader, writer = rendered["users"]

    assert set(reader) == {"bearer_token", "url_map"}
    assert reader["bearer_token"] == SAMPLE_TOKEN
    assert len(reader["url_map"]) == 1
    route = reader["url_map"][0]
    assert set(route) == {"src_paths", "src_query_args", "url_prefix"}
    assert route["src_paths"] == ["/api/v1/query"]
    assert route["src_query_args"] == [f"query={QUERY}"]
    assert route["url_prefix"] == "http://127.0.0.1:8428/"

    assert set(writer) == {"bearer_token", "url_map"}
    assert writer["bearer_token"] == SAMPLE_WRITE_TOKEN
    assert len(writer["url_map"]) == 1
    assert writer["url_map"][0] == {
        "src_paths": ["/api/v1/import/prometheus"],
        "url_prefix": "http://127.0.0.1:8428/?extra_label=writer=agent-quota-mac",
    }


def test_compose_vmauth_service_renders_only_when_enabled():
    service = _compose(True)["services"]["vmauth"]
    assert service["network_mode"] == "host"
    assert service["restart"] == "unless-stopped"
    assert f"-auth.config={CONTAINER_CONFIG}" in service["command"]
    assert f"{HOST_CONFIG}:{CONTAINER_CONFIG}:ro" in service["volumes"]
    assert "vmauth" not in _compose(False)["services"]


def test_config_task_is_mode_0600_no_log_and_removed_when_disabled():
    tasks = yaml.safe_load((ROLE / "tasks/deploy.yml").read_text(encoding="utf-8"))
    render = next(task for task in tasks if task.get("name") == "Render the vmauth quota-route config")
    assert render["ansible.builtin.template"] == {
        "src": "vmauth.yml.j2",
        "dest": "{{ grafana_stack_vmauth_config_host_path }}",
        "owner": "root",
        "group": "root",
        "mode": "0600",
    }
    assert render["when"] == "grafana_stack_vmauth_enabled | bool"
    assert render["no_log"] is True
    remove = next(task for task in tasks if task.get("name") == "Remove the vmauth quota-route config when disabled")
    assert remove["ansible.builtin.file"]["state"] == "absent"
    assert remove["when"] == "not (grafana_stack_vmauth_enabled | bool)"


def test_verify_expects_the_reader_and_writer_routes_and_the_refusals():
    outer = yaml.safe_load((ROLE / "tasks/verify.yml").read_text(encoding="utf-8"))
    deploy_block = outer[0]["block"]
    quota = next(task for task in deploy_block if task.get("name") == "Verify the vmauth quota route")
    checks = {task["name"]: task["ansible.builtin.uri"] for task in quota["block"]}

    assert checks["Verify vmauth answers the authorized quota query"]["status_code"] == 200
    assert checks["Verify vmauth refuses another query with the same token"]["status_code"] == [400, 401, 403]
    assert checks["Verify vmauth refuses a request without a token"]["status_code"] == 401

    write = checks["Verify vmauth accepts a writer import"]
    assert write["method"] == "POST"
    assert write["url"].endswith("/api/v1/import/prometheus")
    assert write["headers"]["Authorization"] == "Bearer {{ grafana_stack_vmauth_write_token }}"
    assert write["status_code"] == 204

    write_on_query = checks["Verify vmauth refuses the writer token on the query route"]
    assert write_on_query["headers"]["Authorization"] == "Bearer {{ grafana_stack_vmauth_write_token }}"
    assert "/api/v1/query?" in write_on_query["url"]
    assert write_on_query["status_code"] == [400, 401, 403]

    read_on_import = checks["Verify vmauth refuses the reader token on the import path"]
    assert read_on_import["method"] == "POST"
    assert read_on_import["url"].endswith("/api/v1/import/prometheus")
    assert read_on_import["headers"]["Authorization"] == "Bearer {{ grafana_stack_vmauth_quota_token }}"
    assert read_on_import["status_code"] == [400, 401, 403]
