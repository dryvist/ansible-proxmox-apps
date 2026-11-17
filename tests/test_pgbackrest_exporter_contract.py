"""pgBackRest exporter package, service and scrape contracts."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "postgres"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _task(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


def test_exporter_package_is_versioned_and_checksum_pinned_per_architecture():
    defaults = _load(ROLE / "defaults" / "main" / "02-pgbackrest.yml")

    assert defaults["postgres_pgbackrest_exporter_version"] == "0.25.0"
    assert defaults["postgres_pgbackrest_exporter_sha256sums"] == {
        "x86_64": "6a6c6450c55ca8461783fbc618f77f3f60a8a7c36d1e75906f8ad4a9585adfde",
        "aarch64": "9a77b124a87464d5fcf42632d4ac0c9f7017868656df81c715baa1ca98b39f6f",
    }
    url = defaults["postgres_pgbackrest_exporter_download_url"]
    assert "woblerr/pgbackrest_exporter/releases/download/v" in url
    assert "postgres_pgbackrest_exporter_version" in url
    assert "pgbackrest_exporter_checksums.txt" in (
        ROLE / "defaults" / "main" / "02-pgbackrest.yml"
    ).read_text(encoding="utf-8")


def test_exporter_package_is_verified_on_the_controller_before_apt_install():
    tasks = _load(ROLE / "tasks" / "pgbackrest.yml")
    stage = _task(tasks, "Stage the checksum-pinned pgBackRest exporter DEB on the controller")
    record = _task(tasks, "Record this host's pgBackRest exporter package for staging")
    install_block = _task(tasks, "Install and enable the pgBackRest exporter")
    install = _task(install_block["block"], "Install the pgBackRest exporter DEB")

    assert stage["ansible.builtin.get_url"]["url"] == "{{ item.url }}"
    assert stage["ansible.builtin.get_url"]["checksum"] == "sha256:{{ item.sha256 }}"
    assert stage["delegate_to"] == "localhost"
    assert stage["run_once"] is True
    assert (
        record["ansible.builtin.set_fact"]["postgres_pgbackrest_exporter_stage_item"][
            "sha256"
        ]
        == "{{ postgres_pgbackrest_exporter_sha256 }}"
    )
    assert install["ansible.builtin.apt"]["deb"] == (
        "/tmp/{{ postgres_pgbackrest_exporter_filename }}"
    )


def test_exporter_service_and_configuration_are_gated_by_pgbackrest_enabled():
    tasks = _load(ROLE / "tasks" / "pgbackrest.yml")
    install_block = _task(tasks, "Install and enable the pgBackRest exporter")
    configure = _task(
        install_block["block"],
        "Configure pgBackRest exporter flags through its environment file",
    )
    service = _task(install_block["block"], "Enable and start pgBackRest exporter")
    disable = _task(tasks, "Stop and disable pgBackRest exporter when backups are disabled")

    assert install_block["when"] == "postgres_pgbackrest_enabled | bool"
    assert configure["ansible.builtin.copy"]["dest"] == "/etc/default/pgbackrest_exporter"
    assert "--backrest.config={{ postgres_pgbackrest_exporter_config_path }}" in (
        configure["ansible.builtin.copy"]["content"]
    )
    assert "--web.listen-address={{ postgres_pgbackrest_exporter_listen_address }}" in (
        configure["ansible.builtin.copy"]["content"]
    )
    assert service["ansible.builtin.systemd_service"]["enabled"] is True
    assert service["ansible.builtin.systemd_service"]["state"] == "started"
    assert disable["when"][0] == "not (postgres_pgbackrest_enabled | bool)"
    assert disable["ansible.builtin.systemd_service"]["enabled"] is False
    assert disable["ansible.builtin.systemd_service"]["state"] == "stopped"
