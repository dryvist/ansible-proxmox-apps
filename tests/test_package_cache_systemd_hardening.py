"""Keep package-cache systemd hardening in one shared template."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SHARED_TEMPLATE = ROOT / "roles/_shared/templates/systemd-service-hardening.conf.j2"
SERVICE_UNITS = (
    ROOT / "roles/devpi_server/templates/devpi-server.service.j2",
    ROOT / "roles/verdaccio_cache/templates/verdaccio-cache.service.j2",
)
SERVICE_TASKS = (
    ROOT / "roles/devpi_server/tasks/main.yml",
    ROOT / "roles/verdaccio_cache/tasks/main.yml",
)
DIRECTIVES = (
    "UMask=0027",
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "ProtectHome=true",
    "ProtectSystem=strict",
    "ProtectKernelTunables=true",
    "ProtectControlGroups=true",
)


def test_package_cache_units_use_the_shared_hardening_template():
    shared = SHARED_TEMPLATE.read_text(encoding="utf-8").splitlines()
    assert shared == list(DIRECTIVES)

    for unit_path, tasks_path in zip(SERVICE_UNITS, SERVICE_TASKS, strict=True):
        unit = unit_path.read_text(encoding="utf-8")
        tasks = tasks_path.read_text(encoding="utf-8")
        assert "{% include _service_hardening_template %}" in unit
        assert "_service_hardening_template: \"{{ role_path }}/../_shared/templates/systemd-service-hardening.conf.j2\"" in tasks
        assert all(directive not in unit for directive in DIRECTIVES)
