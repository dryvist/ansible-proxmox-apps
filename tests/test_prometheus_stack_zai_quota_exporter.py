"""The ZCode quota exporter uses declared modules and a private credential file."""

import json
from pathlib import Path

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/prometheus_stack"


def _defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _render_module_config(defaults):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["to_json"] = json.dumps
    source = (ROLE / "templates/json-exporter.yml.j2").read_text(encoding="utf-8")
    context = dict(defaults, prometheus_stack_json_exporter_credentials={"zcode": "test-fixture"})
    return yaml.safe_load(environment.from_string(source).render(context))


def _render_compose(defaults):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    source = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    loopback_host = defaults["prometheus_stack_blackbox_address"].split(":", maxsplit=1)[0]
    context = dict(
        defaults,
        prometheus_stack_json_exporter_credentials={"zcode": "test-fixture"},
        prometheus_stack_port=9090,
        prometheus_stack_blackbox_port=9115,
        prometheus_stack_blackbox_address=f"{loopback_host}:9115",
        prometheus_stack_json_exporter_address=f"{loopback_host}:7979",
        prometheus_stack_rules_checkout_dir="/opt/prometheus/rules",
        prometheus_stack_json_exporter_config_host_path="/opt/prometheus/json-exporter.yml",
    )
    return yaml.safe_load(environment.from_string(source).render(context))


def test_role_declares_the_executor_url_module_and_window_mapping_once():
    defaults = _defaults()
    executors = defaults["prometheus_stack_json_exporter_executors"]
    assert executors == [
        {
            "name": "zcode",
            "module": "zcode_quota",
            "url": "https://api.z.ai/api/monitor/usage/quota/limit",
            "credential_name": "zcode",
            "credential_path_suffix": "zai_api_key",
            "credentials_file": "/run/secrets/zai_api_key",
            "windows": [
                {"unit": 3, "number": 5, "name": "5h"},
                {"unit": 6, "number": 1, "name": "weekly"},
            ],
        }
    ]
    assert len({executor["credentials_file"] for executor in executors}) == len(executors)
    assert len({executor["credential_path_suffix"] for executor in executors}) == len(executors)


def test_module_renders_bearer_auth_and_quota_series_from_the_declared_windows():
    defaults = _defaults()
    module_name = defaults["prometheus_stack_json_exporter_executors"][0]["module"]
    module = _render_module_config(defaults)["modules"][module_name]

    assert module["fail_on_error"] is True
    assert module["http_client_config"]["authorization"] == {
        "type": "Bearer",
        "credentials_file": defaults["prometheus_stack_json_exporter_executors"][0]["credentials_file"],
    }
    assert module["http_client_config"]["follow_redirects"] is False
    assert [metric["name"] for metric in module["metrics"]] == [
        "agent_quota_api_response_code",
        "agent_quota_used_percent",
        "agent_quota_reset_timestamp_milliseconds",
        "agent_quota_used_percent",
        "agent_quota_reset_timestamp_milliseconds",
    ]

    response_code, used_5h, reset_5h, used_weekly, reset_weekly = module["metrics"]
    assert response_code["path"] == "{.code}"
    assert response_code["labels"] == {"executor": "zcode"}
    for metric, window, unit, number, field in (
        (used_5h, "5h", 3, 5, "percentage"),
        (reset_5h, "5h", 3, 5, "nextResetTime"),
        (used_weekly, "weekly", 6, 1, "percentage"),
        (reset_weekly, "weekly", 6, 1, "nextResetTime"),
    ):
        assert metric["labels"] == {"executor": "zcode", "window": window}
        assert f"@.unit == {unit}" in metric["path"]
        assert f"@.number == {number}" in metric["path"]
        assert metric["path"].endswith(f".{field}}}")
    assert "@.nextResetTime != null" in reset_5h["path"]
    assert "@.nextResetTime != null" in reset_weekly["path"]
    assert "percentage" in used_5h["path"] and "percentage" in used_weekly["path"]


def test_apps_domain_field_reaches_prometheus_and_is_written_for_the_exporter_only():
    group_vars = yaml.safe_load(
        (ROOT / "inventory/group_vars/prometheus_group/60-scrape-configs.yml").read_text(
            encoding="utf-8"
        )
    )
    secret_domains = yaml.safe_load(
        (ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml").read_text(
            encoding="utf-8"
        )
    )
    assert (
        "bao_apps_secrets.zai_api_key"
        in group_vars["prometheus_stack_json_exporter_credentials"]["zcode"]
    )
    assert "prometheus_group" in secret_domains["openbao_secrets_domain_groups"]["apps"]

    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    credential = next(
        task
        for task in tasks
        if task.get("name") == "Install quota credentials for configured json_exporter executors"
    )
    assert credential["ansible.builtin.copy"] == {
        "content": "{{ prometheus_stack_json_exporter_credentials[item.credential_name] }}",
        "dest": "{{ prometheus_stack_data_dir }}/{{ item.credential_path_suffix }}",
        "owner": "{{ prometheus_stack_json_exporter_uid }}",
        "group": "{{ prometheus_stack_json_exporter_gid }}",
        "mode": "0400",
    }
    assert credential["loop"] == "{{ prometheus_stack_json_exporter_executors }}"
    assert (
        credential["when"]
        == "prometheus_stack_json_exporter_credentials.get(item.credential_name, '') | trim | length > 0"
    )
    assert credential["no_log"] is True


def test_exporter_runs_as_the_credential_owner_and_mounts_both_files_read_only():
    defaults = _defaults()
    executor = defaults["prometheus_stack_json_exporter_executors"][0]
    assert executor["credentials_file"] == "/run/secrets/zai_api_key"
    assert "v0.7.0" in defaults["prometheus_stack_json_exporter_image"]

    service = _render_compose(defaults)["services"]["json-exporter"]
    assert service["user"] == f"{defaults['prometheus_stack_json_exporter_uid']}:{defaults['prometheus_stack_json_exporter_gid']}"
    assert service["read_only"] is True
    assert f"--web.listen-address={defaults['prometheus_stack_blackbox_address'].split(':', maxsplit=1)[0]}:7979" in service["command"]
    assert (
        "/opt/prometheus/json-exporter.yml:/etc/json_exporter/config.yml:ro"
        in service["volumes"]
    )
    executor = defaults["prometheus_stack_json_exporter_executors"][0]
    assert (
        f"{defaults['prometheus_stack_data_dir']}/{executor['credential_path_suffix']}"
        f":{executor['credentials_file']}:ro"
        in service["volumes"]
    )
