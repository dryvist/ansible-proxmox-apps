"""Check-mode contracts for remaining first-install service consumers."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def _task(tasks, name):
    return next(task for task in _tasks_in(tasks) if task.get("name") == name)


def _conditions(task):
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def _role_yaml(role, path):
    return yaml.safe_load((REPO / "roles" / role / path).read_text(encoding="utf-8"))


def test_nautobot_service_consumers_skip_unwritten_units():
    main = _role_yaml("nautobot", "tasks/main.yml")
    application = _role_yaml("nautobot", "tasks/application_bringup.yml")
    handlers = _role_yaml("nautobot", "handlers/main.yml")
    unit_probes = {
        "Check for the Nautobot server systemd unit": (
            "nautobot_server_unit_file",
            "/etc/systemd/system/nautobot-server.service",
        ),
        "Check for the Nautobot worker systemd unit": (
            "nautobot_worker_unit_file",
            "/etc/systemd/system/nautobot-worker.service",
        ),
        "Check for the Nautobot scheduler systemd unit": (
            "nautobot_scheduler_unit_file",
            "/etc/systemd/system/nautobot-scheduler.service",
        ),
    }
    main_names = [task.get("name") for task in _tasks_in(main)]

    for name, (register, path) in unit_probes.items():
        probe = _task(main, name)
        assert probe["ansible.builtin.stat"]["path"] == path
        assert probe["register"] == register
        assert probe["when"] == "ansible_check_mode"
        assert main_names.index(name) < main_names.index("Converge the server layer through the collection role")

    application_include = _task(main, "Include the Nautobot application bring-up")
    assert application_include["ansible.builtin.include_tasks"]["file"] == "application_bringup.yml"
    service_gate = _conditions(_task(application, "Enable and start the Nautobot services"))[1]
    for unit, register in (
        ("nautobot-server", "nautobot_server_unit_file"),
        ("nautobot-worker", "nautobot_worker_unit_file"),
        ("nautobot-scheduler", "nautobot_scheduler_unit_file"),
    ):
        assert f"item == '{unit}' and {register}.stat.exists" in service_gate
    assert service_gate.startswith("not ansible_check_mode or")

    handler_gate = _conditions(_task(handlers, "Restart nautobot services"))[1]
    for register, _path in unit_probes.values():
        assert f"{register}.stat.exists" in handler_gate


def test_nautobot_redis_service_steps_skip_a_previewed_package():
    tasks = _role_yaml("nautobot", "tasks/system_and_redis.yml")
    handlers = _role_yaml("nautobot", "handlers/main.yml")
    gate = "not (ansible_check_mode and nautobot_system_packages_install is changed)"

    assert _task(tasks, "Install Nautobot system packages")["register"] == "nautobot_system_packages_install"
    assert _task(tasks, "Enable and start Redis")["when"] == gate
    assert _task(handlers, "Restart redis")["when"] == gate


def test_zammad_service_steps_skip_previewed_package_installs():
    packages = _role_yaml("zammad", "tasks/main/packages_and_signing.yml")
    elasticsearch = _role_yaml("zammad", "tasks/main/elasticsearch_and_package.yml")
    nginx = _role_yaml("zammad", "tasks/main/nginx_and_bootstrap.yml")
    handlers = _role_yaml("zammad", "handlers/main.yml")
    system_gate = "not (ansible_check_mode and zammad_system_packages_install is changed)"
    es_gate = "not (ansible_check_mode and zammad_elasticsearch_install is changed)"

    assert _task(packages, "Install Zammad system packages")["register"] == "zammad_system_packages_install"
    assert _task(packages, "Enable and start Redis")["when"] == system_gate
    assert _task(elasticsearch, "Install Elasticsearch")["register"] == "zammad_elasticsearch_install"
    assert _task(elasticsearch, "Enable and start Elasticsearch")["when"] == es_gate
    assert es_gate in _conditions(_task(elasticsearch, "Wait for Elasticsearch to answer"))

    nginx_service_conditions = _conditions(_task(nginx, "Enable and start the Zammad + nginx services"))
    assert system_gate in nginx_service_conditions
    assert "not (ansible_check_mode and not zammad_configured)" in nginx_service_conditions

    assert _task(handlers, "Restart redis")["when"] == system_gate
    assert es_gate in _conditions(_task(handlers, "Restart elasticsearch"))
    assert system_gate in _conditions(_task(handlers, "Reload nginx"))
    assert "not (ansible_check_mode and not zammad_configured)" in _conditions(_task(handlers, "Restart zammad"))


def test_docker_engine_skips_venv_consumers_after_a_previewed_prerequisite_install():
    tasks = _role_yaml("docker_engine", "tasks/main.yml")
    gate = "not (ansible_check_mode and docker_engine_python_dependencies_install is changed)"

    assert _task(tasks, "Install Python venv and pip for dependencies")["register"] == (
        "docker_engine_python_dependencies_install"
    )
    assert gate in _conditions(_task(tasks, "Create virtualenv for Ansible Python dependencies"))
    assert gate in _conditions(_task(tasks, "Set Python interpreter to use the venv for subsequent tasks"))


def test_docker_daemon_play_skips_hosts_without_dockerd_in_both_modes():
    play = yaml.safe_load(
        (REPO / "playbooks" / "site" / "01a-docker-daemon.yml").read_text(
            encoding="utf-8"
        )
    )[0]
    tasks = play["tasks"]
    probe = _task(tasks, "Check whether the Docker daemon binary is installed")
    assert probe["ansible.builtin.stat"]["path"] == "/usr/bin/dockerd"
    assert probe["register"] == "docker_daemon_dockerd"
    assert "ansible_check_mode" not in str(probe.get("when", ""))

    configure = _task(tasks, "Configure Docker daemon on installed Docker hosts")
    ensure = _task(tasks, "Ensure Docker is running")
    for task in (configure, ensure):
        conditions = _conditions(task)
        assert any("docker_daemon_dockerd.stat.exists" in condition for condition in conditions)
        assert any(
            "inventory_hostname in groups.get('docker_group', [])" in condition
            for condition in conditions
        )

    handlers = _role_yaml("docker_engine", "handlers/main.yml")
    restart = _task(handlers, "Restart docker")
    restart_conditions = _conditions(restart)
    assert any("docker_daemon_dockerd.stat.exists" in condition for condition in restart_conditions)
    assert "inventory_hostname != (plane_host | default(''))" in restart_conditions

    daemon_tasks = _role_yaml("docker_engine", "tasks/daemon_json.yml")
    directory_probe = _task(daemon_tasks, "Check whether the Docker configuration directory exists")
    assert directory_probe["ansible.builtin.stat"]["path"] == "/etc/docker"
    config_write = _task(daemon_tasks, "Configure Docker daemon JSON")
    assert config_write["when"] == (
        "not (ansible_check_mode and not docker_engine_config_directory.stat.exists)"
    )

    engine_tasks = _role_yaml("docker_engine", "tasks/main.yml")
    task_names = [task.get("name") for task in _tasks_in(engine_tasks)]
    assert task_names.index("Install fuse-overlayfs for Docker on ZFS-backed LXC") < task_names.index(
        "Configure the Docker daemon before installing Docker packages"
    )
    assert task_names.index("Configure the Docker daemon before installing Docker packages") < task_names.index(
        "Install Docker packages"
    )
