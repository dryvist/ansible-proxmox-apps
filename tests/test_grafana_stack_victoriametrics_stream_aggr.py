"""VictoriaMetrics combines only the Cribl span-metric deltas per minute."""

from pathlib import Path

import jinja2
from jinja2 import meta
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/grafana_stack"


def test_stream_aggregation_rule_is_rendered_and_mounted_read_only():
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    metrics = defaults["grafana_stack_vm_stream_aggr_metrics"]
    assert metrics == ["llm_span_.*", "agent_runs"]

    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    compose_template = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    compose_context = {
        name: "fixture" for name in meta.find_undeclared_variables(environment.parse(compose_template))
    }
    host_path = "/opt/grafana-stack/stream-aggregation.yml"
    container_path = "/etc/stream-aggregation.yml"
    compose_context.update(
        grafana_stack_vm_stream_aggr_config_host_path=host_path,
        grafana_stack_vm_stream_aggr_config_container_path=container_path,
        grafana_stack_vm_extra_flags=[],
        grafana_stack_provisioning_subdirs=[],
        grafana_stack_allow_embedding=False,
        grafana_stack_litellm_prices_enabled=False,
        grafana_stack_clickhouse_enabled=False,
    )
    compose = yaml.safe_load(environment.from_string(compose_template).render(compose_context))
    victoriametrics = compose["services"]["victoriametrics"]
    assert f"-streamAggr.config={container_path}" in victoriametrics["command"]
    assert f"{host_path}:{container_path}:ro" in victoriametrics["volumes"]

    rule_template = (ROLE / "templates/victoriametrics-stream-aggr.yml.j2").read_text(encoding="utf-8")
    rules = yaml.safe_load(environment.from_string(rule_template).render(defaults))
    assert rules == [{
        "match": '{__name__=~"llm_span_.*|agent_runs"}',
        "interval": "1m",
        "outputs": ["sum_samples"],
        "keep_metric_names": True,
    }]

    deploy_tasks = yaml.safe_load((ROLE / "tasks/deploy.yml").read_text(encoding="utf-8"))
    render_task = next(task for task in deploy_tasks if task.get("name") == "Render VictoriaMetrics stream aggregation config")
    assert render_task["ansible.builtin.template"] == {
        "src": "victoriametrics-stream-aggr.yml.j2",
        "dest": "{{ grafana_stack_vm_stream_aggr_config_host_path }}",
        "owner": "root",
        "group": "root",
        "mode": "0644",
    }
