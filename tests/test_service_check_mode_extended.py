"""Additional role contracts for first-install service actions."""

import pytest

from service_check_mode_contract_support import assert_case

CASES = [
    {
        "role": "vikunja",
        "probes": [("tasks/main.yml", "Check for the Vikunja systemd unit", "vikunja_unit_file", "/etc/systemd/system/vikunja.service")],
        "tasks": [("tasks/main.yml", "Enable and start Vikunja", "not ansible_check_mode or vikunja_unit_file.stat.exists")],
        "handlers": [("Restart vikunja", "not ansible_check_mode or vikunja_unit_file.stat.exists")],
    },
    {
        "role": "traefik",
        "probes": [("tasks/main.yml", "Check for the Traefik systemd unit", "traefik_unit_file", "/etc/systemd/system/traefik.service")],
        "tasks": [("tasks/main.yml", "Enable + start Traefik", "not ansible_check_mode or traefik_unit_file.stat.exists")],
        "handlers": [("Restart traefik", "not ansible_check_mode or traefik_unit_file.stat.exists")],
    },
    {
        "role": "service_deadman",
        "probes": [("tasks/main.yml", "Check for the validator systemd timer unit", "service_deadman_timer_unit_file", "/etc/systemd/system/{{ service_deadman_service_name }}.timer")],
        "tasks": [("tasks/main.yml", "Enable and start the validator timer", "not ansible_check_mode or service_deadman_timer_unit_file.stat.exists")],
        "handlers": [("Reload systemd and restart deadman timer", "not ansible_check_mode or service_deadman_timer_unit_file.stat.exists")],
    },
    {
        "role": "technitium_dns",
        "probes": [("tasks/apex_health_check.yml", "Check for the apex health-check systemd timer unit", "technitium_dns_apex_timer_unit_file", "/etc/systemd/system/technitium-apex-health.timer")],
        "tasks": [("tasks/apex_health_check.yml", "Enable the apex health-check timer", "not ansible_check_mode or technitium_dns_apex_timer_unit_file.stat.exists")],
        "handlers": [("Restart apex health timer", "not ansible_check_mode or technitium_dns_apex_timer_unit_file.stat.exists")],
    },
    {
        "role": "technitium_install",
        "probes": [("tasks/main.yml", "Check for the Technitium DNS systemd unit", "technitium_install_dns_unit_file", "/etc/systemd/system/dns.service")],
        "tasks": [("tasks/main.yml", "Enable and start Technitium DNS", "not ansible_check_mode or technitium_install_dns_unit_file.stat.exists")],
    },
    {
        "role": "ntfy_docker",
        "probes": [
            ("tasks/slack_fanout.yml", "Check for the ntfy-to-slack systemd unit template", "ntfy_docker_slack_unit_file", "/etc/systemd/system/ntfy-to-slack@.service"),
            ("tasks/zammad_subscriber.yml", "Check for the ntfy subscriber systemd unit", "ntfy_docker_subscriber_unit_file", "/etc/systemd/system/ntfy-subscribe.service"),
            ("tasks/canary.yml", "Check for the ntfy canary systemd timer", "ntfy_docker_canary_timer_unit_file", "/etc/systemd/system/ntfy-canary.timer"),
        ],
        "tasks": [
            ("tasks/slack_fanout.yml", "Enable and start every ntfy-to-slack instance", "not ansible_check_mode or ntfy_docker_slack_unit_file.stat.exists"),
            ("tasks/zammad_subscriber.yml", "Enable and start the ntfy subscriber", "not ansible_check_mode or ntfy_docker_subscriber_unit_file.stat.exists"),
            ("tasks/canary.yml", "Enable and start the ntfy canary timer", "not ansible_check_mode or ntfy_docker_canary_timer_unit_file.stat.exists"),
        ],
        "handlers": [
            ("Restart ntfy-to-slack instances", "not ansible_check_mode or ntfy_docker_slack_unit_file.stat.exists"),
            ("Restart ntfy subscriber", "not ansible_check_mode or ntfy_docker_subscriber_unit_file.stat.exists"),
            ("Restart ntfy canary timer", "not ansible_check_mode or ntfy_docker_canary_timer_unit_file.stat.exists"),
        ],
    },
    {
        "role": "agent_sandbox",
        "probes": [
            ("tasks/main/nftables.yml", "Check for the container-egress filter systemd unit", "agent_sandbox_nft_unit_file", "/etc/systemd/system/{{ agent_sandbox_nft_service }}.service"),
            ("tasks/main/ci_resolver.yml", "Check for the CI resolver systemd service unit", "agent_sandbox_ci_resolver_unit_file", "/etc/systemd/system/ci-resolver.service"),
            ("tasks/main/dispatcher_install.yml", "Check for the dispatcher credential-check timer unit", "agent_sandbox_dispatch_check_timer_unit_file", "/etc/systemd/system/agent-dispatch-check.timer"),
            ("tasks/main/docs.yml", "Check for the public docs refresh timer unit", "agent_sandbox_docs_refresh_timer_unit_file", "/etc/systemd/system/agent-sandbox-docs-refresh.timer"),
            ("tasks/main/validate_and_prune.yml", "Check for the session-log spool-prune timer unit", "agent_sandbox_spool_prune_timer_unit_file", "/etc/systemd/system/agent-sandbox-spool-prune.timer"),
        ],
        "tasks": [
            ("tasks/main/nftables.yml", "Enable and start the container-egress filter", "not ansible_check_mode or agent_sandbox_nft_unit_file.stat.exists"),
            ("tasks/main/ci_resolver.yml", "Enable CI resolver and its workbook timers", "not ansible_check_mode or agent_sandbox_ci_resolver_unit_file.stat.exists"),
            ("tasks/main/dispatcher_install.yml", "Enable the hourly dispatcher credential check", "not ansible_check_mode or agent_sandbox_dispatch_check_timer_unit_file.stat.exists"),
            ("tasks/main/docs.yml", "Enable the public docs refresh timer", "not ansible_check_mode or agent_sandbox_docs_refresh_timer_unit_file.stat.exists"),
            ("tasks/main/validate_and_prune.yml", "Enable session-log spool prune timer", "not ansible_check_mode or agent_sandbox_spool_prune_timer_unit_file.stat.exists"),
        ],
        "handlers": [
            ("Reload agent sandbox nftables", "not ansible_check_mode or agent_sandbox_nft_unit_file.stat.exists"),
            ("Restart CI resolver", "not ansible_check_mode or agent_sandbox_ci_resolver_unit_file.stat.exists"),
        ],
    },
    {
        "role": "github_runner",
        "probes": [
            ("tasks/main.yml", "Check for the GitHub runner token agent systemd unit", "github_runner_agent_unit_file", "/etc/systemd/system/openbao-github-runner-agent.service"),
            ("tasks/reconcile_service_units.yml", "Check for optional organization review runner systemd unit templates", "github_runner_review_unit_file_checks", "/etc/systemd/system/github-runner-review-{{ item.org }}@.service"),
            ("tasks/reconcile_service_units.yml", "Check for the standard GitHub runner systemd unit template", "github_runner_unit_file", "/etc/systemd/system/github-runner@.service"),
            ("tasks/data_disk_timers.yml", "Check for the Docker data reclaim systemd timer unit", "github_runner_docker_prune_timer_unit_file", "/etc/systemd/system/github-runner-docker-prune.timer"),
            ("tasks/data_disk_timers.yml", "Check for the Molecule orphan-container reaper systemd timer unit", "github_runner_molecule_reaper_timer_unit_file", "/etc/systemd/system/github-runner-molecule-reaper.timer"),
        ],
        "tasks": [
            ("tasks/main.yml", "Enable and start the runner token agent", "not ansible_check_mode or github_runner_agent_unit_file.stat.exists"),
            ("tasks/reconcile_service_units.yml", "Stop the runner token agent when no replicas are wanted", "not ansible_check_mode or github_runner_agent_unit_file.stat.exists"),
            ("tasks/reconcile_runner_units.yml", "Enable and start the pooled runners", "not ansible_check_mode or github_runner_unit_file.stat.exists"),
            ("tasks/reconcile_review_runner_units.yml", "Enable and start the configured review runners", "not ansible_check_mode or (github_runner_review_unit_file_checks.results | default([]) | selectattr('stat.exists') | list | length) == (github_runner_active_review_orgs | length)"),
            ("tasks/data_disk_timers.yml", "Enable the Docker data reclaim timer", "not ansible_check_mode or github_runner_docker_prune_timer_unit_file.stat.exists"),
            ("tasks/data_disk_timers.yml", "Enable the Molecule orphan-container reaper timer", "not ansible_check_mode or github_runner_molecule_reaper_timer_unit_file.stat.exists"),
        ],
        "handlers": [
            ("Restart the runner token agent", "not ansible_check_mode or github_runner_agent_unit_file.stat.exists"),
            ("Restart github runners", "not ansible_check_mode or github_runner_unit_file.stat.exists"),
            ("Restart review github runners", "not ansible_check_mode or (github_runner_review_unit_file_checks.results | default([]) | selectattr('stat.exists') | list | length) == (github_runner_active_review_orgs | length)"),
        ],
    },
    {
        "role": "cribl_stream",
        "probes": [
            ("tasks/main.yml", "Check for the Cribl Stream systemd unit", "cribl_stream_unit_file", "/etc/systemd/system/cribl.service"),
            ("tasks/github_actions.yml", "Check for the Cribl OpenBao Agent systemd unit", "cribl_stream_github_actions_agent_unit_file", "/etc/systemd/system/{{ cribl_stream_github_actions_agent_service }}"),
        ],
        "tasks": [
            ("tasks/main.yml", "Ensure Cribl Stream service is running", "not ansible_check_mode or cribl_stream_unit_file.stat.exists"),
            ("tasks/main.yml", "Rotate the management API admin credential off the vendor default", "not ansible_check_mode or cribl_stream_unit_file.stat.exists"),
            ("tasks/github_actions.yml", "Enable and start the Cribl OpenBao Agent proxy", "not ansible_check_mode or cribl_stream_github_actions_agent_unit_file.stat.exists"),
        ],
        "handlers": [
            ("Restart cribl stream", "not ansible_check_mode or cribl_stream_unit_file.stat.exists"),
            ("Restart Cribl OpenBao Agent", "not ansible_check_mode or cribl_stream_github_actions_agent_unit_file.stat.exists"),
        ],
    },
    {
        "role": "postgres",
        "installs": [("tasks/main/install_and_create_cluster.yml", "Install PostgreSQL from PGDG", "postgres_package_install")],
        "probes": [
            ("tasks/main/patroni_bootstrap.yml", "Check for the Patroni systemd unit", "postgres_ha_patroni_unit_file_check", "/etc/systemd/system/patroni.service"),
            ("tasks/main/pg_dump_backups.yml", "Check for the pg_dump backup systemd service unit", "postgres_pg_dump_service_unit_file", "/etc/systemd/system/pg-backup.service"),
            ("tasks/main/pg_dump_backups.yml", "Check for the pg_dump backup systemd timer unit", "postgres_pg_dump_timer_unit_file", "/etc/systemd/system/pg-backup.timer"),
            ("tasks/pgbackrest.yml", "Check for pgBackRest backup timer unit files", "postgres_pgbackrest_timer_unit_files", "/etc/systemd/system/pgbackrest-backup@{{ item.type }}.timer"),
        ],
        "tasks": [
            ("tasks/main/install_and_create_cluster.yml", "Ensure the PostgreSQL cluster service is started and enabled", "not (ansible_check_mode and postgres_package_install is changed)"),
            ("tasks/main/cluster_config.yml", "Restart the cluster when it is bound loopback-only", "not (ansible_check_mode and postgres_package_install is changed)"),
            ("tasks/main/patroni_bootstrap.yml", "Ensure the Patroni service is started and enabled", "not ansible_check_mode or postgres_ha_patroni_unit_file_check.stat.exists"),
            ("tasks/main/pg_dump_backups.yml", "Enable and start the pg_dump backup timer", "not ansible_check_mode or postgres_pg_dump_timer_unit_file.stat.exists"),
            ("tasks/pgbackrest.yml", "Enable and start each pgBackRest backup timer", "not ansible_check_mode or (postgres_pgbackrest_timer_unit_files.results | default([]) | selectattr('stat.exists') | list | length) == (postgres_pgbackrest_schedules | length)"),
            ("tasks/main/standby_bootstrap.yml", "Stop the cluster before reinitializing PGDATA", "not (ansible_check_mode and postgres_package_install is changed)"),
            ("tasks/main/standby_bootstrap.yml", "Start the cluster in standby mode", "not (ansible_check_mode and postgres_package_install is changed)"),
            ("tasks/pgbackrest.yml", "Stop the cluster before restoring", "not (ansible_check_mode and postgres_package_install is changed)"),
            ("tasks/pgbackrest.yml", "Start the cluster to replay WAL", "not (ansible_check_mode and postgres_package_install is changed)"),
            ("tasks/main/dr_restore.yml", "Take a fresh backup so the comparison sees current data", "not ansible_check_mode or postgres_pg_dump_service_unit_file.stat.exists | default(false)"),
        ],
        "handlers": [
            ("Reload postgresql", "not (ansible_check_mode and (postgres_package_install | default({}) is changed))"),
            ("Restart postgresql", "not (ansible_check_mode and (postgres_package_install | default({}) is changed))"),
            ("Restart patroni", "not ansible_check_mode or postgres_ha_patroni_unit_file_check.stat.exists | default(true)"),
        ],
    },
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["role"])
def test_first_install_service_actions_have_check_mode_gates(case):
    assert_case(case)
