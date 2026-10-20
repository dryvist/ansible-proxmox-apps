"""Read-only health probes that must execute in Ansible check mode."""

from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PROBES = (
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify both stack containers are running",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify VictoriaMetrics answers /health",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify grafana answers /api/health",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify the provisioned datasource resolves in grafana",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Capture stack diagnostics on failure",
    ),
    (
        "roles/apt_recovery/tasks/main.yml",
        "Wait for package-manager locks to clear",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Wait for Cribl Edge services to be ready",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Wait for Cribl Stream services to be ready",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Verify Cribl Edge health",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Verify Cribl Stream health",
    ),
    (
        "roles/healthchecks_docker/tasks/main.yml",
        "Verify healthchecks login page renders",
    ),
    (
        "roles/n8n_docker/tasks/main.yml",
        "Verify n8n /healthz endpoint",
    ),
    (
        "roles/n8n_docker/tasks/main.yml",
        "Read n8n frontend settings (owner-setup state)",
    ),
    (
        "roles/status_stack/tasks/main.yml",
        "Verify Gatus answers /",
    ),
    (
        "roles/status_stack/tasks/main.yml",
        "Probe whether Uptime Kuma still needs initial setup",
    ),
    (
        "roles/object_storage/tasks/iam_provision_bucket_role.yml",
        "Read the current canned policies for this bucket",
    ),
    (
        "roles/object_storage/tasks/infra_mirrors.yml",
        "Resolve pointer URLs for missing pointer-based infra artifacts",
    ),
    (
        "roles/ssh_ca_trust/tasks/main.yml",
        "Read the effective sshd configuration",
    ),
    (
        "roles/ssh_ca_trust/tasks/main.yml",
        "Assert a static authorized_key still exists for the converge user",
    ),
    (
        "roles/proxmox_backup_server/tasks/main.yml",
        "List the configured datastores",
    ),
    (
        "roles/proxmox_backup_server/tasks/main.yml",
        "Re-read the datastores after creation",
    ),
    (
        "roles/postgres/handlers/main.yml",
        "Wait for etcd to answer after a restart",
    ),
    (
        "roles/postgres/handlers/main.yml",
        "Wait for patroni to answer after a restart",
    ),
    (
        "roles/postgres/tasks/main/patroni_bootstrap.yml",
        "Wait for this node's Patroni process to come up",
    ),
    (
        "roles/postgres/tasks/main/patroni_bootstrap.yml",
        "Wait for this node's Patroni REST API to report PostgreSQL running",
    ),
    (
        "roles/postgres/tasks/main/patroni_bootstrap.yml",
        "Wait for the cluster to elect a leader",
    ),
    (
        "roles/technitium_dns/tasks/main/build_records.yml",
        "Read this node's live zone type (authoritative over any heuristic)",
    ),
    (
        "roles/technitium_dns/tasks/main/validate_and_auth.yml",
        "Authenticate to this node's Technitium API (per-host session token)",
    ),
    (
        "roles/technitium_dns/tasks/main/build_records.yml",
        "Check if DNS zone exists",
    ),
    (
        "roles/technitium_dns/tasks/main/infra_a_records.yml",
        "Get existing A records for zone",
    ),
    (
        "roles/technitium_dns/tasks/main/infra_a_records.yml",
        "Look up retired guest A records",
    ),
    ("roles/technitium_dns/tasks/query_log.yml", "List installed DNS apps"),
    (
        "roles/technitium_dns/tasks/query_log.yml",
        "Re-read the DNS app list after install or update",
    ),
    (
        "roles/technitium_dns/tasks/query_log.yml",
        "Read the live Log Exporter app config",
    ),
    (
        "roles/technitium_dns/tasks/main/read_soa_serial.yml",
        "Read this node's zone SOA serial",
    ),
    (
        "roles/technitium_install/tasks/main.yml",
        "Read the frameworks the active muxer can resolve",
    ),
    (
        "roles/technitium_install/tasks/main.yml",
        "Wait for Technitium to start",
    ),
    ("roles/cadvisor/tasks/main.yml", "Verify cAdvisor metrics endpoint"),
    ("roles/haproxy/tasks/main.yml", "Verify Nginx is listening on UDP ports"),
    (
        "roles/homeassistant/tasks/main.yml",
        "Verify Home Assistant is responding",
    ),
    ("roles/homarr/tasks/main.yml", "Verify Homarr answers over HTTP"),
    (
        "roles/idrac_kvm_docker/tasks/main.yml",
        "Verify each iDRAC KVM HTTP endpoint responds",
    ),
    ("roles/immich/tasks/main.yml", "Verify the Immich server responds"),
    (
        "roles/mailpit_docker/tasks/main.yml",
        "Verify Mailpit web UI health",
    ),
    (
        "roles/mcp_gateway/tasks/main.yml",
        "Wait for the gateway to answer its health endpoint",
    ),
    (
        "roles/nautobot/tasks/main.yml",
        "Wait for the Nautobot web UI to answer",
    ),
    ("roles/netmon/tasks/main.yml", "Verify the Telegraf container is running"),
    (
        "roles/network_quality/tasks/main.yml",
        "Verify the smokeping_prober container is running",
    ),
    (
        "roles/network_quality/tasks/main.yml",
        "Verify smokeping_prober is serving metrics",
    ),
    ("roles/ntfy_docker/tasks/main.yml", "Verify ntfy health endpoint"),
    (
        "roles/openproject_docker/tasks/main.yml",
        "Verify OpenProject health endpoint",
    ),
    ("roles/phpipam/tasks/main.yml", "Verify phpIPAM is responding"),
    (
        "roles/prometheus_pve_exporter/tasks/main.yml",
        "Verify pve-exporter answers its health endpoint",
    ),
    (
        "roles/prometheus_stack/tasks/main.yml",
        "Verify both stack containers are running",
    ),
    (
        "roles/prometheus_stack/tasks/main.yml",
        "Verify prometheus is healthy and ready",
    ),
    (
        "roles/prometheus_stack/tasks/main.yml",
        "Verify the blackbox exporter answers /-/healthy",
    ),
    (
        "roles/prometheus_stack/tasks/main.yml",
        "Verify the blackbox exporter completes an ICMP probe",
    ),
    (
        "roles/prometheus_stack/tasks/main.yml",
        "Verify Prometheus has scraped probe_success into the TSDB",
    ),
    (
        "roles/unifi_metrics/tasks/main.yml",
        "Verify the unpoller and telegraf containers are running",
    ),
    (
        "roles/vikunja/tasks/main.yml",
        "Wait for Vikunja to answer its info endpoint",
    ),
    (
        "roles/wall/tasks/main.yml",
        "Wait for the reloaded workers to serve a relative directory redirect",
    ),
    (
        "roles/zammad/tasks/main/search_and_health.yml",
        "Wait for the Zammad web UI to answer through nginx",
    ),
    (
        "roles/zammad/tasks/main/search_and_health.yml",
        "Wait for the Zammad web UI to answer after the restart",
    ),
    (
        "roles/zammad/tasks/main/elasticsearch_and_package.yml",
        "Wait for Elasticsearch to answer",
    ),
    (
        "roles/zot_registry/tasks/main.yml",
        "Wait for zot registry API to be ready",
    ),
    (
        "roles/technitium_install/tasks/upgrade.yml",
        "Wait for Technitium to come back after the upgrade",
    ),
    (
        "roles/cribl_stream/tasks/upgrade.yml",
        "Wait for Cribl Stream to come back after the upgrade",
    ),
)

FIRST_INSTALL_GUARDS = {
    ("roles/cadvisor/tasks/main.yml", "Verify cAdvisor metrics endpoint"): "cadvisor_compose",
    ("roles/homeassistant/tasks/main.yml", "Verify Home Assistant is responding"): "homeassistant_compose",
    ("roles/homarr/tasks/main.yml", "Verify Homarr answers over HTTP"): "homarr_installer",
    ("roles/idrac_kvm_docker/tasks/main.yml", "Verify each iDRAC KVM HTTP endpoint responds"): "idrac_kvm_docker_compose",
    ("roles/immich/tasks/main.yml", "Verify the Immich server responds"): "immich_compose",
    ("roles/mailpit_docker/tasks/main.yml", "Verify Mailpit web UI health"): "mailpit_docker_compose",
    ("roles/mcp_gateway/tasks/main.yml", "Wait for the gateway to answer its health endpoint"): "mcp_gateway_service",
    ("roles/nautobot/tasks/main.yml", "Wait for the Nautobot web UI to answer"): "nautobot_server_binary",
    ("roles/netmon/tasks/main.yml", "Verify the Telegraf container is running"): "netmon_compose",
    ("roles/network_quality/tasks/main.yml", "Verify the smokeping_prober container is running"): "network_quality_compose",
    ("roles/network_quality/tasks/main.yml", "Verify smokeping_prober is serving metrics"): "network_quality_compose",
    ("roles/ntfy_docker/tasks/main.yml", "Verify ntfy health endpoint"): "ntfy_docker_compose",
    ("roles/openproject_docker/tasks/main.yml", "Verify OpenProject health endpoint"): "openproject_docker_compose",
    ("roles/phpipam/tasks/main.yml", "Verify phpIPAM is responding"): "phpipam_compose",
    ("roles/prometheus_pve_exporter/tasks/main.yml", "Verify pve-exporter answers its health endpoint"): "prometheus_pve_exporter_compose",
    ("roles/prometheus_stack/tasks/main.yml", "Verify both stack containers are running"): "prometheus_stack_compose",
    ("roles/prometheus_stack/tasks/main.yml", "Verify prometheus is healthy and ready"): "prometheus_stack_compose",
    ("roles/prometheus_stack/tasks/main.yml", "Verify the blackbox exporter answers /-/healthy"): "prometheus_stack_compose",
    ("roles/prometheus_stack/tasks/main.yml", "Verify the blackbox exporter completes an ICMP probe"): "prometheus_stack_compose",
    ("roles/prometheus_stack/tasks/main.yml", "Verify Prometheus has scraped probe_success into the TSDB"): "prometheus_stack_compose",
    ("roles/unifi_metrics/tasks/main.yml", "Verify the unpoller and telegraf containers are running"): "unifi_metrics_compose",
    ("roles/vikunja/tasks/main.yml", "Wait for Vikunja to answer its info endpoint"): "vikunja_service",
    ("roles/wall/tasks/main.yml", "Wait for the reloaded workers to serve a relative directory redirect"): "wall_nginx_service",
    ("roles/zammad/tasks/main/search_and_health.yml", "Wait for the Zammad web UI to answer through nginx"): "zammad_searchindex_marker",
    ("roles/zammad/tasks/main/search_and_health.yml", "Wait for the Zammad web UI to answer after the restart"): "zammad_searchindex_marker",
    ("roles/zot_registry/tasks/main.yml", "Wait for zot registry API to be ready"): "zot_registry_service",
    ("roles/zammad/tasks/main/elasticsearch_and_package.yml", "Wait for Elasticsearch to answer"): "zammad_es_service",
}

REGISTERED_RESULTS = (
    ("roles/cadvisor/tasks/main.yml", "Deploy cAdvisor via docker compose", "cadvisor_compose"),
    (
        "roles/homeassistant/tasks/main.yml",
        "Deploy Home Assistant via docker compose",
        "homeassistant_compose",
    ),
    (
        "roles/homarr/tasks/main.yml",
        "Install Homarr via the pinned community-scripts installer",
        "homarr_installer",
    ),
    (
        "roles/idrac_kvm_docker/tasks/main.yml",
        "Deploy idrac-kvm containers via docker compose",
        "idrac_kvm_docker_compose",
    ),
    ("roles/immich/tasks/main.yml", "Deploy the Immich stack via docker compose", "immich_compose"),
    ("roles/mailpit_docker/tasks/main.yml", "Deploy Mailpit via docker compose", "mailpit_docker_compose"),
    ("roles/mcp_gateway/tasks/main.yml", "Enable and start mcp-gateway", "mcp_gateway_service"),
    (
        "roles/nautobot/tasks/main.yml",
        "Read whether the Nautobot server binary exists",
        "nautobot_server_binary",
    ),
    ("roles/netmon/tasks/main.yml", "Deploy netmon stack via docker compose", "netmon_compose"),
    (
        "roles/network_quality/tasks/main.yml",
        "Deploy the network_quality stack via docker compose",
        "network_quality_compose",
    ),
    ("roles/ntfy_docker/tasks/main.yml", "Deploy ntfy via docker compose", "ntfy_docker_compose"),
    (
        "roles/openproject_docker/tasks/main.yml",
        "Deploy OpenProject via docker compose",
        "openproject_docker_compose",
    ),
    ("roles/phpipam/tasks/main.yml", "Deploy phpipam via docker compose", "phpipam_compose"),
    (
        "roles/prometheus_pve_exporter/tasks/main.yml",
        "Deploy pve-exporter via docker compose",
        "prometheus_pve_exporter_compose",
    ),
    (
        "roles/prometheus_stack/tasks/main.yml",
        "Deploy the prometheus stack via docker compose",
        "prometheus_stack_compose",
    ),
    (
        "roles/unifi_metrics/tasks/main.yml",
        "Deploy unifi_metrics stack via docker compose",
        "unifi_metrics_compose",
    ),
    ("roles/vikunja/tasks/main.yml", "Enable and start Vikunja", "vikunja_service"),
    ("roles/wall/tasks/main.yml", "Enable and start nginx", "wall_nginx_service"),
    ("roles/zot_registry/tasks/main.yml", "Enable and start zot service", "zot_registry_service"),
    (
        "roles/zammad/tasks/main/elasticsearch_and_package.yml",
        "Enable and start Elasticsearch",
        "zammad_es_service",
    ),
)

SKIPPED_PROBE_FOLLOWUPS = (
    (
        "roles/netmon/tasks/main.yml",
        "Capture Telegraf diagnostics when it is not running",
    ),
    (
        "roles/netmon/tasks/main.yml",
        "Fail with Telegraf diagnostics when the container is not running",
    ),
    (
        "roles/unifi_metrics/tasks/main.yml",
        "Capture diagnostics when a container is not running",
    ),
    (
        "roles/unifi_metrics/tasks/main.yml",
        "Fail with diagnostics when a container is not running",
    ),
)


def _tasks_in(value):
    if isinstance(value, list):
        for item in value:
            yield from _tasks_in(item)
    elif isinstance(value, dict):
        if "name" in value:
            yield value
        for key in ("block", "rescue", "always"):
            if key in value:
                yield from _tasks_in(value[key])


@pytest.mark.parametrize(("relative_path", "task_name"), PROBES)
def test_read_only_health_probes_run_in_check_mode(relative_path, task_name):
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task = next((task for task in _tasks_in(tasks) if task.get("name") == task_name), None)

    assert task is not None, f"Task not found: {task_name}"
    assert task.get("check_mode") is False
    assert task.get("changed_when") is False
    if (
        relative_path == "roles/grafana_stack/tasks/main.yml"
        and task_name != "Capture stack diagnostics on failure"
    ):
        when = task.get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert "grafana_stack_compose" in condition
    if (
        relative_path == "roles/proxmox_backup_server/tasks/main.yml"
        and task_name == "Re-read the datastores after creation"
    ):
        when = task.get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert "proxmox_backup_server_datastore_list" in condition
    guard = FIRST_INSTALL_GUARDS.get((relative_path, task_name))
    if guard:
        when = task.get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert guard in condition


@pytest.mark.parametrize(("relative_path", "task_name", "register_name"), REGISTERED_RESULTS)
def test_first_install_probe_guards_use_registered_results(relative_path, task_name, register_name):
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task = next((task for task in _tasks_in(tasks) if task.get("name") == task_name), None)

    assert task is not None, f"Task not found: {task_name}"
    assert task.get("register") == register_name


@pytest.mark.parametrize(("relative_path", "task_name"), SKIPPED_PROBE_FOLLOWUPS)
def test_check_mode_skipped_probes_skip_their_followups(relative_path, task_name):
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task = next((task for task in _tasks_in(tasks) if task.get("name") == task_name), None)

    assert task is not None, f"Task not found: {task_name}"
    when = task.get("when", "")
    condition = " ".join(when) if isinstance(when, list) else when
    assert ".skipped | default(false)" in condition


def test_node_exporter_stage_result_gates_check_mode_unpack_and_binary_copy():
    relative_path = "roles/node_exporter/tasks/main.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    stage = task_by_name["Stage the pinned node_exporter release tarball on the controller"]
    assert stage.get("register") == "node_exporter_release_stage"
    assert stage.get("run_once") is True
    assert "throttle" not in stage
    assert "ansible_play_hosts" in stage["loop"]
    assert "unique(attribute='node_exporter_release')" in stage["loop"]
    assert "item.node_exporter_download_url" in stage["ansible.builtin.get_url"]["url"]
    assert "item.node_exporter_release" in stage["ansible.builtin.get_url"]["dest"]
    assert "item.node_exporter_sha256sums_url" in stage["ansible.builtin.get_url"]["checksum"]

    critical_assert = task_by_name["Assert critical variables are defined and valid"]
    assert "ansible_facts['architecture'] in ['x86_64', 'aarch64']" in critical_assert["ansible.builtin.assert"]["that"]
    assert any("node_exporter_version is defined" in condition for condition in critical_assert["ansible.builtin.assert"]["that"])
    assert any("node_exporter_port is defined" in condition for condition in critical_assert["ansible.builtin.assert"]["that"])
    assert all(
        "default_ipv4" not in condition
        for condition in critical_assert["ansible.builtin.assert"]["that"]
    )

    for task_name in (
        "Unpack the node_exporter release",
        "Install the node_exporter binary",
    ):
        condition = task_by_name[task_name].get("when", "")
        assert "not ansible_check_mode" in condition
        assert "node_exporter_release_stage.changed" in condition


def test_technitium_check_mode_skips_query_log_followups_when_install_is_skipped():
    tasks = yaml.safe_load((REPO / "roles/technitium_dns/tasks/query_log.yml").read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    guarded_tasks = (
        "Re-read the DNS app list after install or update",
        "Require the Log Exporter app to have actually loaded",
        "Read the live Log Exporter app config",
        "Compute the desired Log Exporter config (app config + our syslog block)",
        "Configure Log Exporter syslog export (drift-gated)",
    )
    for task_name in guarded_tasks:
        when = task_by_name[task_name].get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert "technitium_dns_query_log_app_installed" in condition

    for task_name in (
        "Install the Log Exporter app from the internal object-storage mirror",
        "Update the Log Exporter app to the pinned version",
        "Configure Log Exporter syslog export (drift-gated)",
    ):
        when = task_by_name[task_name].get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert task_by_name[task_name].get("check_mode") is not False


def test_technitium_write_result_assertion_skips_check_mode():
    tasks = yaml.safe_load(
        (REPO / "roles/technitium_dns/tasks/main/infra_a_records.yml").read_text(encoding="utf-8")
    )
    task = next(
        task for task in _tasks_in(tasks)
        if task.get("name") == "Assert the infrastructure A records were actually written"
    )
    when = task.get("when", "")
    condition = " ".join(when) if isinstance(when, list) else when
    assert "not ansible_check_mode" in condition
