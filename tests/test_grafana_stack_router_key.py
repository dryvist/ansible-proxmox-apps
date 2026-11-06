"""Exercise the shared router-key read and missing-key assertion without a store."""

from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template


TASKS = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "roles/grafana_stack/tasks/llm_router.yml").read_text()
)


def test_router_key_read_is_controller_only_and_never_writes():
    read = TASKS[0]
    request = read["ansible.builtin.uri"]
    assert request["method"] == "GET"
    assert request["url"].endswith("/v1/secret/data/apps/grafana-llm")
    assert request["headers"]["X-Vault-Token"] == "{{ lookup('env', 'BAO_TOKEN') }}"
    assert request["status_code"] == [200, 404]
    assert read["delegate_to"] == "localhost"
    assert read["become"] is False
    assert read["vars"]["ansible_become"] is False
    assert read["check_mode"] is False
    assert read["no_log"] is True
    assert TASKS[1]["no_log"] is True


@pytest.mark.parametrize(
    "response, expected",
    [
        ({"status": 404}, False),
        ({"json": {"data": {"data": {}}}}, False),
        ({"json": {"data": {"data": {"grafana_llm_router_key": ""}}}}, False),
        ({"json": {"data": {"data": {"grafana_llm_router_key": "  "}}}}, False),
        ({"json": {"data": {"data": {"grafana_llm_router_key": "sk-fixture"}}}}, True),
    ],
)
def test_missing_router_key_fails_the_production_assertion(response, expected):
    templar = Templar(loader=DataLoader(), variables={
        "grafana_stack_router_secret": response,
        "bao_apps_secrets": {"grafana_llm_router_key": "sk-unused-fallback"},
    })
    expression = TASKS[1]["ansible.builtin.set_fact"]["grafana_stack_effective_llm_router_key"]
    key = templar.template(trust_as_template(expression))
    templar.available_variables = {"grafana_stack_effective_llm_router_key": key}
    assertion = TASKS[2]["ansible.builtin.assert"]
    assert templar.evaluate_conditional(trust_as_template(assertion["that"][0])) is expected
    assert "apps/grafana-llm" in assertion["fail_msg"]
    assert "grafana_llm_router_key" in assertion["fail_msg"]
    if expected:
        assert key == "sk-fixture"
