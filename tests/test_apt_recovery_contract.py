"""Contract checks for bounded package-lock recovery before Homarr installs."""

from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template


ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _render(expression, **variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(expression))


BROKEN_AUDIT = """The following packages are in a mess due to serious problems during
installation. They must be reinstalled for them (and any packages
that depend on them) to function properly:
 libpython3.13-stdlib:amd64 Standard library for Python

The following packages have been unpacked but not yet configured.
They must be configured using dpkg --configure or the configure
menu option in dselect for them to work:
 python3.13           Interactive high-level object-oriented language
"""


def test_recovery_precedes_homarr_package_install_and_long_installer_is_polled():
    tasks = _load(ROOT / "roles/homarr/tasks/main.yml")
    recovery_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.import_role", {}).get("name") == "apt_recovery"
    )
    apt_index = next(
        index
        for index, task in enumerate(tasks)
        if "ansible.builtin.apt" in task
    )
    installer = next(
        task
        for task in tasks
        if task.get("name") == "Install Homarr via the pinned community-scripts installer"
    )

    assert recovery_index < apt_index
    assert installer["async"] == "{{ homarr_install_timeout }}"
    assert installer["poll"] > 0


def test_lock_wait_is_bounded_and_recovery_only_runs_for_incomplete_dpkg():
    defaults = _load(ROOT / "roles/apt_recovery/defaults/main.yml")
    tasks = _load(ROOT / "roles/apt_recovery/tasks/main.yml")

    lock_wait = tasks[0]
    audit_index = next(
        index for index, task in enumerate(tasks) if "dpkg" in task.get("ansible.builtin.command", {}).get("argv", [])
    )
    configure_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.command", {}).get("argv") == ["dpkg", "--configure", "-a"]
    )
    configure = tasks[configure_index]

    assert lock_wait["retries"] == "{{ apt_recovery_lock_retries }}"
    assert lock_wait["delay"] == "{{ apt_recovery_lock_delay }}"
    assert lock_wait["changed_when"] is False
    assert defaults["apt_recovery_lock_retries"] * defaults["apt_recovery_lock_delay"] < 240
    assert audit_index == 1
    assert configure_index > audit_index
    assert "apt_recovery_audit.stdout" in configure["when"]
    assert configure["changed_when"]
    assert tasks[-1]["always"][-1]["failed_when"]


@pytest.mark.parametrize(
    "audit",
    [
        BROKEN_AUDIT,
        BROKEN_AUDIT.replace(" Standard library for Python", "").replace(
            "           Interactive high-level object-oriented language", ""
        ),
    ],
    ids=["package-descriptions", "package-names-only"],
)
def test_fix_broken_uses_audited_package_names_and_forbids_removals(audit):
    tasks = _load(ROOT / "roles/apt_recovery/tasks/main.yml")
    recovery = tasks[-1]
    post_audit, repair = recovery["block"]
    apt = repair["ansible.builtin.apt"]

    assert post_audit["ansible.builtin.command"]["argv"] == ["dpkg", "--audit"]
    assert post_audit["register"] == "apt_recovery_post_audit"
    assert recovery["environment"]["LC_ALL"] == "C"
    assert apt == {
        "name": "{{ apt_recovery_packages }}",
        "state": "fixed",
        "force_apt_get": True,
        "autoremove": False,
        "fail_on_autoremove": True,
    }
    packages = _render(
        repair["vars"]["apt_recovery_packages"],
        apt_recovery_post_audit={"stdout": audit},
    )
    assert packages == ["libpython3.13-stdlib:amd64", "python3.13"]
    assert _render(apt["name"], apt_recovery_packages=packages) == packages
    assert _render("{{ " + repair["when"] + " }}", apt_recovery_packages=packages)
    assert not _render("{{ " + repair["when"] + " }}", apt_recovery_packages=[])


@pytest.mark.parametrize("return_code,failed", [(0, False), (1, False), (2, True)])
def test_dpkg_processing_errors_reach_fix_broken_but_fatal_errors_stop(return_code, failed):
    configure = _load(ROOT / "roles/apt_recovery/tasks/main.yml")[2]
    assert _render(
        "{{ " + configure["failed_when"] + " }}",
        apt_recovery_configure={"rc": return_code},
    ) is failed


@pytest.mark.parametrize("audit,needs_recovery", [("", False), (BROKEN_AUDIT, True)])
def test_clean_audit_skips_configuration_and_repair(audit, needs_recovery):
    tasks = _load(ROOT / "roles/apt_recovery/tasks/main.yml")
    for task in (tasks[2], tasks[-1]):
        assert _render(
            "{{ " + task["when"] + " }}",
            apt_recovery_audit={"stdout": audit, "stderr": ""},
        ) is needs_recovery


@pytest.mark.parametrize(
    "audit,failed",
    [
        ({"rc": 0, "stdout": "", "stderr": ""}, False),
        ({"rc": 0, "stdout": BROKEN_AUDIT, "stderr": ""}, True),
        ({"rc": 0, "stdout": "", "stderr": "dpkg warning"}, True),
        ({"rc": 2, "stdout": "", "stderr": ""}, True),
    ],
)
def test_final_audit_fails_real_runs_and_reports_in_check_mode(audit, failed):
    tasks = _load(ROOT / "roles/apt_recovery/tasks/main.yml")
    recovery = tasks[-1]
    post_audit, repair = recovery["block"]
    final_audit = recovery["always"][-1]

    # Only read-only probes force execution in check mode. dpkg configuration
    # skips normally, apt simulates, and neither bypasses the final real audit.
    assert tasks[1]["check_mode"] is False
    assert "check_mode" not in tasks[2]
    assert post_audit["check_mode"] is False
    assert "check_mode" not in repair
    assert final_audit["check_mode"] is False
    assert "when" not in final_audit
    assert final_audit["ansible.builtin.command"]["argv"] == ["dpkg", "--audit"]
    assert final_audit["changed_when"] is False
    assert _render(
        "{{ " + final_audit["failed_when"] + " }}",
        apt_recovery_final_audit=audit,
        ansible_check_mode=False,
    ) is failed
    assert _render(
        "{{ " + final_audit["failed_when"] + " }}",
        apt_recovery_final_audit=audit,
        ansible_check_mode=True,
    ) is False
