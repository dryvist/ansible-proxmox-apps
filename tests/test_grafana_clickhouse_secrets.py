"""Exercise the real catalog scoping, controller publication and datasource render."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from secrets_collection_support import HOMELAB_ROLES, SECRETS_DOMAIN_CATALOG

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "playbooks/tasks"
SCOPE = TASKS / "scope_grafana_clickhouse_secrets.yml"
FILTER = TASKS / "filter_grafana_clickhouse_secrets.yml"
MAP = ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml"
PREFETCH = ROOT / "playbooks/site/00-load-and-telemetry.yml"
TEMPLATE = ROOT / "roles/grafana_stack/templates/datasource.yml.j2"


def _yaml(path):
    return yaml.safe_load(path.read_text())


def _render(value, variables):
    if not isinstance(value, str):
        return value
    return Templar(loader=DataLoader(), variables=variables).template(
        trust_as_template(value)
    )


def _apply(task, variables):
    context = dict(variables)
    context.update({key: trust_as_template(value) for key, value in task.get("vars", {}).items()})
    conditions = task.get("when", [])
    if isinstance(conditions, str):
        conditions = [conditions]
    if all(_render("{{ " + condition + " }}", context) for condition in conditions):
        facts = {
            key: _render(value, context)
            for key, value in task["ansible.builtin.set_fact"].items()
        }
        if task.get("delegate_facts"):
            variables["hostvars"][task["delegate_to"]].update(facts)
        else:
            variables.update(facts)


def _scope(flag=None, *, in_scope=True, full_consumer=None):
    groups = {"grafana_group": ["dashboard"]}
    active = ["grafana_group"]
    hosts = ["dashboard"] if in_scope else ["other"]
    if full_consumer:
        active.append(full_consumer)
    variables = {
        "groups": groups,
        "ansible_play_hosts_all": hosts,
        "openbao_secrets_active_groups": active,
        "openbao_secrets_domain_groups_source": _yaml(MAP)["openbao_secrets_domain_groups"],
        "openbao_secrets_catalog": _yaml(SECRETS_DOMAIN_CATALOG),
        "hostvars": {"localhost": {}, "dashboard": {}},
    }
    if flag is not None:
        variables["hostvars"]["dashboard"]["grafana_stack_clickhouse_enabled"] = flag
    for task in _yaml(SCOPE):
        for item in _render(task["loop"], variables):
            variables["item"] = item
            _apply(task, variables)
    variables["openbao_secrets_domains"] = variables["openbao_secrets_catalog"]["openbao_secrets_domains"]
    variables["openbao_secrets_domain_groups"] = variables["openbao_secrets_domain_groups_source"]
    for task in _yaml(HOMELAB_ROLES / "openbao_secrets/tasks/narrow_domains.yml"):
        if "loop" in task:
            for item in _render(task["loop"], variables):
                variables["item"] = item
                _apply(task, variables)
        else:
            _apply(task, variables)
    return variables


def _clickhouse_reads(variables):
    return [
        path for domain in variables["openbao_secrets_domains_to_fetch"]
        if domain["name"] == "clickhouse" for path in domain["paths"]
    ]


@pytest.mark.parametrize("flag,in_scope", [(None, True), (False, True), ("false", True), (True, False)])
def test_disabled_or_out_of_scope_grafana_adds_no_secret_read(flag, in_scope):
    variables = _scope(flag, in_scope=in_scope)
    assert _clickhouse_reads(variables) == []
    assert variables["openbao_secrets_domain_groups_source"] == _yaml(MAP)["openbao_secrets_domain_groups"]
    assert variables["openbao_secrets_catalog"] == _yaml(SECRETS_DOMAIN_CATALOG)


@pytest.mark.parametrize("flag", [True, "true"])
def test_enabled_grafana_reads_one_document_and_publishes_only_reader_key(flag):
    variables = _scope(flag)
    assert _clickhouse_reads(variables) == ["ai/clickhouse"]
    controller = variables["hostvars"]["localhost"]
    controller["openbao_secrets_by_domain"] = {
        "apps": {"unrelated": "fixture"},
        "clickhouse": {"GRAFANA_PASSWORD": "fixture-$reader", "APP_PASSWORD": "fixture-writer"},
    }
    for task in _yaml(FILTER):
        assert task["no_log"] and task["delegate_facts"] and task["run_once"]
        _apply(task, variables)
    assert controller["openbao_secrets_by_domain"] == {
        "apps": {"unrelated": "fixture"}, "clickhouse": {"GRAFANA_PASSWORD": "fixture-$reader"},
    }
    expression = _yaml(ROOT / "inventory/group_vars/grafana_group.yml")["grafana_stack_clickhouse_password"]
    assert _render(expression, variables) == "fixture-$reader"
    assert "bao_clickhouse_secrets" not in variables
    assert "bao_clickhouse_secrets" not in variables["hostvars"]["dashboard"]


@pytest.mark.parametrize("consumer", ["clickhouse_group", "langfuse_group"])
def test_database_consumers_keep_full_catalog_and_credentials(consumer):
    variables = _scope(True, full_consumer=consumer)
    domain = next(d for d in _yaml(SECRETS_DOMAIN_CATALOG)["openbao_secrets_domains"] if d["name"] == "clickhouse")
    assert _clickhouse_reads(variables) == domain["paths"]
    result = {"clickhouse": {"APP_PASSWORD": "fixture-writer", "GRAFANA_PASSWORD": "fixture-reader"}}
    variables["hostvars"]["localhost"]["openbao_secrets_by_domain"] = deepcopy(result)
    for task in _yaml(FILTER):
        _apply(task, variables)
    assert variables["hostvars"]["localhost"]["openbao_secrets_by_domain"] == result


def test_prefetch_orders_scoping_before_reads_and_filtering_before_publication():
    play = next(p for p in _yaml(PREFETCH) if p["name"] == "Pre-fetch resource-domain secrets from OpenBao")
    tasks = play["tasks"][0]["block"]
    actions = [t.get("ansible.builtin.import_tasks", "fetch" if "ansible.builtin.include_role" in t else "") for t in tasks]
    assert actions.index("../tasks/load_openbao_secrets_catalog.yml") < actions.index("../tasks/scope_grafana_clickhouse_secrets.yml")
    assert actions.index("../tasks/scope_grafana_clickhouse_secrets.yml") < actions.index("fetch")
    assert actions.index("fetch") < actions.index("../tasks/filter_grafana_clickhouse_secrets.yml")
    assert actions.index("../tasks/filter_grafana_clickhouse_secrets.yml") < actions.index("../tasks/publish_secret_domain_facts.yml")
    fetch = tasks[actions.index("fetch")]
    assert "openbao_secrets_domain_groups_source" in fetch["vars"]["openbao_secrets_domain_groups"]


def _datasource_variables(enabled, prices):
    defaults = _yaml(ROOT / "roles/grafana_stack/defaults/main.yml")
    defaults.update(_yaml(ROOT / "inventory/group_vars/grafana_group.yml"))
    variables = {k: trust_as_template(v) if isinstance(v, str) else v for k, v in defaults.items()}
    variables.update({
        "grafana_stack_clickhouse_enabled": enabled,
        "grafana_stack_litellm_prices_enabled": prices,
        "grafana_stack_clickhouse_host": "analytics.example.test",
        "grafana_stack_clickhouse_port": 18123,
        "grafana_stack_prometheus_url": "",
        "hostvars": {"localhost": {"openbao_secrets_by_domain": {
            "clickhouse": {"GRAFANA_PASSWORD": "fixture-$reader"},
        }}},
    })
    return variables


def test_clickhouse_endpoint_uses_the_tagged_guest_name_and_published_port():
    variables = _datasource_variables(True, True)
    del variables["grafana_stack_clickhouse_host"]
    del variables["grafana_stack_clickhouse_port"]
    variables.update({
        "ingress_domain": "example.test",
        "tofu_data": {
            "constants": {"service_ports": {"clickhouse_http": 18123}},
            "containers": {"arbitrary-key": {
                "hostname": "analytics", "ip": "192.0.2.10", "tags": ["clickhouse"],
            }},
        },
    })
    defaults = _yaml(ROOT / "roles/grafana_stack/defaults/main.yml")
    variables.update({k: trust_as_template(defaults[k]) for k in (
        "grafana_stack_clickhouse_host", "grafana_stack_clickhouse_port",
    )})
    rendered = yaml.safe_load(_render(TEMPLATE.read_text(), variables))
    datasource = next(d for d in rendered["datasources"] if d["uid"] == "clickhouse")
    assert datasource["jsonData"]["host"] == "analytics.example.test"
    assert datasource["jsonData"]["port"] == 18123


@pytest.mark.parametrize("prices", [True, False])
@pytest.mark.parametrize("prometheus_url", ["", "https://metrics.example.test"])
def test_enabled_to_disabled_removes_clickhouse_and_preserves_other_datasources(prices, prometheus_url):
    variables = _datasource_variables(True, prices)
    variables["grafana_stack_prometheus_url"] = prometheus_url
    enabled = yaml.safe_load(_render(TEMPLATE.read_text(), variables))
    datasource = next(d for d in enabled["datasources"] if d["uid"] == "clickhouse")
    assert datasource["secureJsonData"] == {"password": "fixture-$$reader"}
    assert "deleteDatasources" not in enabled

    variables["grafana_stack_clickhouse_enabled"] = False
    variables["hostvars"] = {}
    disabled_text = _render(TEMPLATE.read_text(), variables)
    disabled = yaml.safe_load(disabled_text)
    assert all(d["uid"] != "clickhouse" for d in disabled["datasources"])
    assert disabled["deleteDatasources"] == [{"name": datasource["name"], "orgId": 1}]
    assert "fixture" not in disabled_text and "secureJsonData" not in disabled_text
    assert disabled["datasources"] == [
        d for d in enabled["datasources"] if d["uid"] != "clickhouse"
    ]


@pytest.mark.parametrize("domain", [{}, {"GRAFANA_PASSWORD": ""}])
def test_missing_or_empty_controller_reader_password_is_rejected(domain):
    variables = _datasource_variables(True, True)
    variables["hostvars"]["localhost"]["openbao_secrets_by_domain"]["clickhouse"] = domain
    with pytest.raises(Exception, match="ClickHouse reader password missing from OpenBao"):
        _render(TEMPLATE.read_text(), variables)
