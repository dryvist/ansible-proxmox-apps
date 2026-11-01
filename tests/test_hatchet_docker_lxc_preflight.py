"""hatchet_docker fails fast when its LXC lacks the fuse/keyctl features Docker needs."""

from pathlib import Path

import yaml

TASKS = Path(__file__).resolve().parents[1] / "roles/hatchet_docker/tasks/main.yml"


def _tasks():
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _named(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


def test_preflight_runs_before_any_docker_work():
    names = [task.get("name") for task in _tasks()]
    gate = names.index("Require the LXC features Docker needs")
    assert names.index("Check for /dev/fuse inside the container") < gate
    assert names.index("Probe whether the keyctl syscall is allowed") < gate
    assert gate < names.index("Deploy Hatchet via Docker Compose")


def test_gate_requires_both_fuse_and_keyctl_on_lxc_only():
    tasks = _tasks()
    gate = _named(tasks, "Require the LXC features Docker needs")
    that = " ".join(gate["ansible.builtin.assert"]["that"])
    assert "hatchet_docker_dev_fuse.stat.ischr" in that
    assert "hatchet_docker_keyctl_probe.rc == 0" in that
    assert "docker_lxc_features" in gate["ansible.builtin.assert"]["fail_msg"]
    for name in (
        "Check for /dev/fuse inside the container",
        "Probe whether the keyctl syscall is allowed",
        "Require the LXC features Docker needs",
    ):
        assert _named(tasks, name)["when"] == "ansible_virtualization_type | default('') == 'lxc'"


def test_keyctl_probe_treats_only_enosys_as_missing():
    probe = _named(_tasks(), "Probe whether the keyctl syscall is allowed")
    code = probe["ansible.builtin.command"]["argv"][-1]
    compile(code, "keyctl-probe", "exec")
    assert "errno.ENOSYS" in code
    assert "sys.exit(3 if" in code
    assert probe["failed_when"] == "hatchet_docker_keyctl_probe.rc not in [0, 3]"
    assert probe["changed_when"] is False
