"""The ZCode quota exporter uses declared modules and a private credential file."""

import json
from pathlib import Path

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/prometheus_stack"

CONTRACT_METRICS = (
    ("agent_quota_used_percent", "used_percent"),
    ("agent_quota_window_seconds", "window_seconds"),
    ("agent_quota_reset_timestamp_seconds", "reset_timestamp_seconds"),
)


def _defaults():
    merged = {}
    for path in sorted((ROLE / "defaults/main").glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")))
    return merged


def _render_module_config(defaults, **extra):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["to_json"] = json.dumps
    environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    source = (ROLE / "templates/json-exporter.yml.j2").read_text(encoding="utf-8")
    context = dict(
        defaults,
        prometheus_stack_json_exporter_credentials={"zcode": "test-fixture"},
    )
    context.update(extra)
    return yaml.safe_load(environment.from_string(source).render(context))


def _render_module_text(defaults, **extra):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["to_json"] = json.dumps
    environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    source = (ROLE / "templates/json-exporter.yml.j2").read_text(encoding="utf-8")
    context = dict(
        defaults,
        prometheus_stack_json_exporter_credentials={"zcode": "test-fixture"},
    )
    context.update(extra)
    return environment.from_string(source).render(context)


def _render_compose(defaults, active_executors=None):
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    source = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    loopback_host = defaults["prometheus_stack_blackbox_address"].split(":", maxsplit=1)[0]
    if active_executors is None:
        active_executors = defaults["prometheus_stack_json_exporter_executors"]
    context = dict(
        defaults,
        prometheus_stack_json_exporter_credentials={"zcode": "test-fixture"},
        prometheus_stack_json_exporter_active_executors=active_executors,
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
    assert defaults["prometheus_stack_json_exporter_quota_enabled"] is False
    executors = defaults["prometheus_stack_json_exporter_executors"]
    assert executors == [
        {
            "name": "zcode",
            "module": "zcode_quota",
            "url": "https://api.z.ai/api/monitor/usage/quota/limit",
            "credential_name": "zcode",
            "credential_path_suffix": "zai_api_key",
            "credentials_file": "/run/secrets/zai_api_key",
            "response_paths": {
                "used_percent": "{.data.limits[?(@.unit == {unit} && @.number == {number})].percentage}",
                "window_seconds": "{.data.limits[?(@.unit == {unit} && @.number == {number})].windowSeconds}",
                "reset_timestamp_seconds": (
                    "{.data.limits[?(@.unit == {unit} && @.number == {number} "
                    "&& @.nextResetTime != null)].nextResetTimeSeconds}"
                ),
            },
            "windows": [
                {"unit": 3, "number": 5, "name": "5h"},
                {"unit": 6, "number": 1, "name": "weekly"},
            ],
        }
    ]
    assert set(executors[0]["response_paths"]) == {field for _, field in CONTRACT_METRICS}
    assert len({executor["credentials_file"] for executor in executors}) == len(executors)
    assert len({executor["credential_path_suffix"] for executor in executors}) == len(executors)


def test_module_renders_bearer_auth_and_the_contract_series_for_both_windows():
    defaults = _defaults()
    executor = defaults["prometheus_stack_json_exporter_executors"][0]
    module_name = executor["module"]
    module = _render_module_config(defaults, prometheus_stack_json_exporter_quota_enabled=True)["modules"][module_name]

    assert module["fail_on_error"] is True
    assert module["http_client_config"]["authorization"] == {
        "type": "Bearer",
        "credentials_file": executor["credentials_file"],
    }
    assert module["http_client_config"]["follow_redirects"] is False

    metrics = module["metrics"]
    assert [metric["name"] for metric in metrics] == [
        name for window in executor["windows"] for name, _ in CONTRACT_METRICS
    ]

    rendered = {
        (metric["labels"]["window"], metric["name"]): metric for metric in metrics
    }
    for window in executor["windows"]:
        for name, field in CONTRACT_METRICS:
            metric = rendered[(window["name"], name)]
            assert metric["type"] == "value"
            assert metric["labels"] == {"executor": executor["name"], "window": window["name"]}
            assert metric["path"] == (
                executor["response_paths"][field]
                .replace("{unit}", str(window["unit"]))
                .replace("{number}", str(window["number"]))
            )
    reset_paths = [
        metric["path"]
        for (window_name, name), metric in rendered.items()
        if name == "agent_quota_reset_timestamp_seconds"
    ]
    assert all("@.nextResetTime != null" in path for path in reset_paths)
    assert {"5h", "weekly"} == {window["name"] for window in executor["windows"]}


def test_disabled_flag_renders_the_files_without_the_feature():
    defaults = _defaults()
    assert defaults["prometheus_stack_json_exporter_quota_enabled"] is False

    # With the flag off the exporter config is byte for byte the render the
    # role produces without the feature: no module, no credential reference.
    assert _render_module_text(defaults, prometheus_stack_json_exporter_quota_enabled=False) == "modules:\n"
    assert _render_module_text(defaults, prometheus_stack_json_exporter_quota_enabled=False) == _render_module_text(
        defaults, prometheus_stack_json_exporter_credentials={}
    )

    # The compose file renders without the exporter service or its mounts.
    compose = _render_compose(defaults, active_executors=[])
    assert "json-exporter" not in compose["services"]


def test_enabled_flag_never_exposes_the_key_value_and_mounts_paths_only():
    defaults = _defaults()
    executor = defaults["prometheus_stack_json_exporter_executors"][0]
    key_value = "secret-fixture-key-value"

    module_environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    module_environment.filters["to_json"] = json.dumps
    module_environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    module_source = (ROLE / "templates/json-exporter.yml.j2").read_text(encoding="utf-8")
    module_render = module_environment.from_string(module_source).render(
        dict(
            defaults,
            prometheus_stack_json_exporter_credentials={"zcode": key_value},
            prometheus_stack_json_exporter_quota_enabled=True,
        )
    )
    compose_environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    compose_environment.filters["bool"] = lambda value: value is True or str(value).lower() == "true"
    compose_source = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    loopback_host = defaults["prometheus_stack_blackbox_address"].split(":", maxsplit=1)[0]
    compose_render = compose_environment.from_string(compose_source).render(
        dict(
            defaults,
            prometheus_stack_json_exporter_credentials={"zcode": key_value},
            prometheus_stack_json_exporter_active_executors=defaults["prometheus_stack_json_exporter_executors"],
            prometheus_stack_port=9090,
            prometheus_stack_blackbox_port=9115,
            prometheus_stack_blackbox_address=f"{loopback_host}:9115",
            prometheus_stack_json_exporter_address=f"{loopback_host}:7979",
            prometheus_stack_rules_checkout_dir="/opt/prometheus/rules",
            prometheus_stack_json_exporter_config_host_path="/opt/prometheus/json-exporter.yml",
        )
    )
    for rendered_text in (module_render, compose_render):
        assert key_value not in rendered_text

    module_config = yaml.safe_load(module_render)
    authorization = module_config["modules"][executor["module"]]["http_client_config"]["authorization"]
    assert authorization["credentials_file"] == executor["credentials_file"]
    assert executor["credentials_file"] in module_render

    compose = yaml.safe_load(compose_render)
    volumes = compose["services"]["json-exporter"]["volumes"]
    host_credential_path = f"{defaults['prometheus_stack_data_dir']}/{executor['credential_path_suffix']}"
    assert f"{host_credential_path}:{executor['credentials_file']}:ro" in volumes
    # The exporter config knows only the in-container key path, never the
    # host path where the key material is written.
    assert host_credential_path not in module_render


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
    assert credential["when"] == (
        "prometheus_stack_json_exporter_quota_enabled | bool "
        "and prometheus_stack_json_exporter_credentials.get(item.credential_name, '') | trim | length > 0"
    )
    assert credential["no_log"] is True

    removal = next(
        task
        for task in tasks
        if task.get("name") == "Remove quota credentials for disabled executors or without provisioned keys"
    )
    assert removal["ansible.builtin.file"]["state"] == "absent"
    assert removal["when"] == (
        "not (prometheus_stack_json_exporter_quota_enabled | bool) "
        "or prometheus_stack_json_exporter_credentials.get(item.credential_name, '') | trim | length == 0"
    )
    assert removal["no_log"] is True


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
    assert (
        f"{defaults['prometheus_stack_data_dir']}/{executor['credential_path_suffix']}"
        f":{executor['credentials_file']}:ro"
        in service["volumes"]
    )
