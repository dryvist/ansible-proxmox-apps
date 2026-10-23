"""Check-mode contracts for first-install service actions."""

import pytest

from service_check_mode_contract_support import assert_case

CASES = [
    {
        "role": "apt_cacher_ng",
        "installs": [("tasks/main.yml", "Install apt-cacher-ng package", "apt_cacher_ng_package_install")],
        "tasks": [("tasks/main.yml", "Enable apt-cacher-ng service", "not (ansible_check_mode and apt_cacher_ng_package_install is changed)")],
        "handlers": [("Restart apt-cacher-ng", "not (ansible_check_mode and apt_cacher_ng_package_install is changed)")],
    },
    {
        "role": "zot_registry",
        "probes": [("tasks/main.yml", "Check for the zot systemd unit", "zot_registry_unit_file", "/etc/systemd/system/zot.service")],
        "tasks": [("tasks/main.yml", "Enable and start zot service", "not ansible_check_mode or zot_registry_unit_file.stat.exists")],
        "handlers": [("Restart zot", "not ansible_check_mode or zot_registry_unit_file.stat.exists")],
    },
    {
        "role": "ntp",
        "installs": [("tasks/main.yml", "Install chrony and tzdata", "ntp_chrony_install")],
        "tasks": [
            ("tasks/main.yml", "Set the chrony service state for this host type", "not (ansible_check_mode and ntp_chrony_install is changed)"),
            ("tasks/main.yml", "Remove the check-mode staging file", "ansible_check_mode"),
        ],
        "check_mode": [
            ("tasks/main.yml", "Render the chrony configuration to a staging file", False),
            ("tasks/main.yml", "Remove the check-mode staging file", False),
        ],
        "handlers": [("Restart chrony", "not (ansible_check_mode and ntp_chrony_install is changed)")],
    },
    {
        "role": "proxmox_backup_server",
        "installs": [("tasks/main.yml", "Install Proxmox Backup Server", "proxmox_backup_server_package_install")],
        "tasks": [("tasks/main.yml", "Start and enable the Proxmox Backup Server services", "not (ansible_check_mode and proxmox_backup_server_package_install is changed)")],
    },
    {
        "role": "git_mirror",
        "installs": [("tasks/main.yml", "Install Git mirror packages", "git_mirror_packages_install")],
        "probes": [
            ("tasks/main.yml", "Check for the Git mirror OpenBao Agent systemd unit", "git_mirror_agent_unit_file", "/etc/systemd/system/openbao-git-mirror-agent.service"),
            ("tasks/main.yml", "Check for the Git mirror sync systemd service unit", "git_mirror_sync_service_unit_file", "/etc/systemd/system/git-mirror-sync.service"),
            ("tasks/main.yml", "Check for the Git mirror sync systemd timer unit", "git_mirror_sync_timer_unit_file", "/etc/systemd/system/git-mirror-sync.timer"),
        ],
        "tasks": [
            ("tasks/main.yml", "Enable the OpenBao Agent", "not ansible_check_mode or git_mirror_agent_unit_file.stat.exists"),
            ("tasks/main.yml", "Run the initial Git mirror sync", "not ansible_check_mode or git_mirror_sync_service_unit_file.stat.exists"),
            ("tasks/main.yml", "Enable the Git mirror refresh timer", "not ansible_check_mode or git_mirror_sync_timer_unit_file.stat.exists"),
            ("tasks/main.yml", "Start Apache and apply pending configuration", "not (ansible_check_mode and git_mirror_packages_install is changed)"),
        ],
        "handlers": [
            ("Restart git-mirror OpenBao Agent", "not ansible_check_mode or git_mirror_agent_unit_file.stat.exists"),
            ("Restart git-mirror Apache", "not (ansible_check_mode and git_mirror_packages_install is changed)"),
        ],
    },
    {
        "role": "object_storage",
        "probes": [
            ("tasks/main.yml", "Check for the object-storage systemd unit", "object_storage_unit_file", "/etc/systemd/system/object-storage.service"),
            ("tasks/offsite.yml", "Check for the object-storage offsite timer unit", "object_storage_offsite_timer_unit_file", "/etc/systemd/system/object-storage-offsite@.timer"),
        ],
        "tasks": [
            ("tasks/main.yml", "Enable and start object-storage service", "not ansible_check_mode or object_storage_unit_file.stat.exists"),
            ("tasks/offsite.yml", "Enable and start one offsite timer per bucket", "not ansible_check_mode or object_storage_offsite_timer_unit_file.stat.exists"),
        ],
        "handlers": [
            ("Restart object-storage", "not ansible_check_mode or object_storage_unit_file.stat.exists"),
            ("Restart object-storage offsite timers", "not ansible_check_mode or object_storage_offsite_timer_unit_file.stat.exists"),
        ],
    },
    {
        "role": "static_site",
        "installs": [("tasks/main.yml", "Install nginx", "static_site_nginx_install")],
        "tasks": [("tasks/main.yml", "Ensure nginx is running and enabled", "not (ansible_check_mode and static_site_nginx_install is changed)")],
        "handlers": [("Reload nginx", "not (ansible_check_mode and ((static_site_nginx_install | default(true)) is changed))")],
    },
    {
        "role": "keepalived",
        "installs": [("tasks/main.yml", "Install keepalived", "keepalived_install")],
        "tasks": [("tasks/main.yml", "Enable + start keepalived", "not (ansible_check_mode and keepalived_install is changed)")],
        "handlers": [("Restart keepalived", "not (ansible_check_mode and keepalived_install is changed)")],
    },
    {
        "role": "haproxy",
        "installs": [
            ("tasks/main.yml", "Install HAProxy package", "haproxy_package_install"),
            ("tasks/main.yml", "Install Nginx packages", "haproxy_nginx_install"),
        ],
        "tasks": [
            ("tasks/main.yml", "Start HAProxy service", "not (ansible_check_mode and haproxy_package_install is changed)"),
            ("tasks/main.yml", "Verify HAProxy is running", "not (ansible_check_mode and haproxy_package_install is changed)"),
            ("tasks/main.yml", "Start Nginx service", "not (ansible_check_mode and haproxy_nginx_install is changed)"),
            ("tasks/main.yml", "Verify Nginx is running", "not (ansible_check_mode and haproxy_nginx_install is changed)"),
            ("tasks/main.yml", "Restart Nginx to bind UDP listeners when any are missing", "not (ansible_check_mode and haproxy_nginx_install is changed)"),
        ],
        "handlers": [
            ("Reload haproxy", "not (ansible_check_mode and haproxy_package_install is changed)"),
            ("Restart nginx", "not (ansible_check_mode and haproxy_nginx_install is changed)"),
        ],
    },
    {
        "role": "mcp_gateway",
        "probes": [("tasks/main.yml", "Check for the mcp-gateway systemd unit", "mcp_gateway_unit_file", "/etc/systemd/system/mcp-gateway.service")],
        "tasks": [("tasks/main.yml", "Enable and start mcp-gateway", "not ansible_check_mode or mcp_gateway_unit_file.stat.exists")],
        "handlers": [("Restart mcp-gateway", "not ansible_check_mode or mcp_gateway_unit_file.stat.exists")],
    },
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["role"])
def test_first_install_service_actions_have_check_mode_gates(case):
    assert_case(case)
