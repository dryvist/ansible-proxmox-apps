"""vmauth gives one bearer token one instant query and refuses everything else."""

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
QUERY = '{__name__=~"agent_quota_(used_percent|window_seconds|reset_timestamp_seconds)"}'
SAMPLE_TOKEN = "fixture-quota-reader-token"
HOST_CONFIG = "/opt/grafana-stack/vmauth.yml"
CONTAINER_CONFIG = "/etc/vmauth/config.yml"
VMAUTH_TOKEN_TASKS = yaml.safe_load((ROLE / "tasks/vmauth_token.yml").read_text(encoding="utf-8"))


def _defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


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


def test_quota_token_is_read_from_the_agent_quota_bucket_only_when_enabled():
    defaults = _defaults()
    assert defaults["grafana_stack_vmauth_enabled"] is False
    assert defaults["grafana_stack_vmauth_quota_token"] == ""
    read, resolve, require = VMAUTH_TOKEN_TASKS
    request = read["ansible.builtin.uri"]
    assert request["method"] == "GET"
    assert request["url"].endswith("/v1/secret/data/apps/agent-quota")
    assert request["headers"]["X-Vault-Token"] == "{{ lookup('env', 'BAO_TOKEN') }}"
    assert request["status_code"] == [200, 404]
    assert read["delegate_to"] == "localhost"
    assert read["no_log"] is True
    assert resolve["no_log"] is True
    assert require["ansible.builtin.assert"]["fail_msg"] == (
        "OpenBao bucket apps/agent-quota is missing field agent_quota_reader_token"
    )
    for task in VMAUTH_TOKEN_TASKS:
        assert task["when"] == "grafana_stack_vmauth_enabled | bool"


@pytest.mark.parametrize(
    "response, expected",
    [
        ({"status": 404}, False),
        ({"json": {"data": {"data": {}}}}, False),
        ({"json": {"data": {"data": {"agent_quota_reader_token": ""}}}}, False),
        ({"json": {"data": {"data": {"agent_quota_reader_token": "  "}}}}, False),
        ({"json": {"data": {"data": {"agent_quota_reader_token": SAMPLE_TOKEN}}}}, True),
    ],
)
def test_missing_quota_token_fails_the_assertion(response, expected):
    templar = Templar(loader=DataLoader(), variables={"grafana_stack_vmauth_secret": response})
    expression = VMAUTH_TOKEN_TASKS[1]["ansible.builtin.set_fact"]["grafana_stack_vmauth_quota_token"]
    token = templar.template(trust_as_template(expression))
    templar.available_variables = {"grafana_stack_vmauth_quota_token": token}
    assertion = VMAUTH_TOKEN_TASKS[2]["ansible.builtin.assert"]
    assert templar.evaluate_conditional(trust_as_template(assertion["that"][0])) is expected
    if expected:
        assert token == SAMPLE_TOKEN


def test_deploy_reads_the_quota_token_before_the_config_renders():
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


def test_vmauth_config_has_one_user_and_one_exact_query_route():
    rendered = yaml.safe_load(_render("vmauth.yml.j2", {
        "grafana_stack_vmauth_quota_token": SAMPLE_TOKEN,
        "grafana_stack_vmauth_quota_expr": _defaults()["grafana_stack_vmauth_quota_expr"],
        "grafana_stack_vm_port": 8428,
    }))
    assert list(rendered) == ["users"]
    assert len(rendered["users"]) == 1
    user = rendered["users"][0]
    assert set(user) == {"bearer_token", "url_map"}
    assert user["bearer_token"] == SAMPLE_TOKEN
    assert len(user["url_map"]) == 1
    route = user["url_map"][0]
    assert set(route) == {"src_paths", "src_query_args", "url_prefix"}
    assert route["src_paths"] == ["/api/v1/query"]
    assert route["src_query_args"] == [f"query={QUERY}"]
    assert route["url_prefix"] == "http://127.0.0.1:8428/"


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


def test_verify_expects_the_authorized_query_refusals_and_a_missing_token_refusal():
    outer = yaml.safe_load((ROLE / "tasks/verify.yml").read_text(encoding="utf-8"))
    deploy_block = outer[0]["block"]
    quota = next(task for task in deploy_block if task.get("name") == "Verify the vmauth quota route")
    checks = {task["name"]: task["ansible.builtin.uri"] for task in quota["block"]}
    assert checks["Verify vmauth answers the authorized quota query"]["status_code"] == 200
    assert checks["Verify vmauth refuses another query with the same token"]["status_code"] == [400, 401, 403]
    assert checks["Verify vmauth refuses a request without a token"]["status_code"] == 401
