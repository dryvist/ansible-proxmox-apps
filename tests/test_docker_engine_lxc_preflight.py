"""docker_engine fails fast when its LXC lacks the keyctl/fuse features Docker needs."""

from pathlib import Path

import yaml

TASKS = Path(__file__).resolve().parents[1] / "roles/docker_engine/tasks/main.yml"
LXC = "ansible_facts['virtualization_type'] | default('') == 'lxc'"
GATE_TASKS = (
    "Check for /dev/fuse inside the container",
    "Probe whether the keyctl syscall is allowed",
    "Require the LXC features Docker needs",
)


def _tasks():
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _named(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


def test_role_gathers_the_virtualization_fact_itself_before_the_gate():
    # Guards against a silent skip: the gate keys on virtualization_type, so the
    # role must gather it even when the calling play sets gather_facts: false.
    tasks = _tasks()
    names = [task.get("name") for task in tasks]
    setup = _named(tasks, "Gather OS facts")
    assert "ansible_virtualization_type" in setup["ansible.builtin.setup"]["filter"]
    assert "when" not in setup
    assert names.index("Gather OS facts") < min(names.index(name) for name in GATE_TASKS)


def test_gate_runs_before_any_package_or_daemon_work():
    names = [task.get("name") for task in _tasks()]
    gate = names.index("Require the LXC features Docker needs")
    assert gate < names.index("Install Docker prerequisites")
    assert gate < names.index("Install fuse-overlayfs for Docker on ZFS-backed LXC")


def test_gate_requires_keyctl_and_fuse_when_fuse_overlayfs_is_used_on_lxc_only():
    tasks = _tasks()
    gate = _named(tasks, "Require the LXC features Docker needs")
    that = " ".join(gate["ansible.builtin.assert"]["that"])
    assert "docker_engine_keyctl_probe.rc == 0" in that
    assert "docker_engine_dev_fuse.stat.ischr" in that
    assert "not (docker_engine_install_fuse_overlayfs | bool)" in that
    assert "docker_lxc_features" in gate["ansible.builtin.assert"]["fail_msg"]
    for name in GATE_TASKS:
        assert _named(tasks, name)["when"] == LXC


def test_keyctl_probe_treats_only_enosys_as_missing():
    probe = _named(_tasks(), "Probe whether the keyctl syscall is allowed")
    code = probe["ansible.builtin.command"]["argv"][-1]
    compile(code, "keyctl-probe", "exec")
    assert "errno.ENOSYS" in code
    assert '"x86_64": 250' in code
    assert probe["failed_when"] == "docker_engine_keyctl_probe.rc not in [0, 3]"
    assert probe["changed_when"] is False
    assert probe["check_mode"] is False
