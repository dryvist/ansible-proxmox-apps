"""Keep Homarr's slow module loops and duplicate restarts out of the converge."""

import importlib.util
from pathlib import Path

import yaml
from jinja2 import Template
from ansible.playbook.play_context import PlayContext
from ansible.plugins.loader import connection_loader
from ansible_collections.community.proxmox.plugins.connection import proxmox_pct_remote


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/homarr"
PCT_ADAPTER = ROOT / "plugins/connection/pct_remote_persistent.py"


def _named(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


def test_trusted_certificates_share_the_environment_restart():
    main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    includes = [task["ansible.builtin.include_tasks"] for task in main
                if "ansible.builtin.include_tasks" in task]
    assert includes.index("trusted_certificates.yml") < includes.index("configure.yml")

    trusted = yaml.safe_load((ROLE / "tasks/trusted_certificates.yml").read_text())
    assert not any(task.get("ansible.builtin.meta") == "flush_handlers" for task in trusted)

    configure = yaml.safe_load((ROLE / "tasks/configure.yml").read_text())
    apply_before_api = _named(configure, "Apply any environment change before touching the API")
    assert apply_before_api["ansible.builtin.meta"] == "flush_handlers"


def test_converger_files_deploy_in_one_copy_and_keep_the_entrypoint_executable():
    integrations = yaml.safe_load((ROLE / "tasks/integrations.yml").read_text())
    deploy = _named(integrations, "Deploy the Homarr API converger")
    assert "loop" not in deploy
    assert deploy["ansible.builtin.copy"]["src"] == "{{ role_path }}/files/"
    assert deploy["ansible.builtin.copy"]["mode"] == "preserve"

    run = _named(integrations, "Converge the API key, every integration, and the board tiles")
    assert run["ansible.builtin.command"]["cmd"] == "/usr/local/libexec/homarr/homarr_api.py"
    assert (ROLE / "files/homarr_api.py").stat().st_mode & 0o111


def test_pct_adapter_uses_ansible_persistent_connections():
    spec = importlib.util.spec_from_file_location("pct_remote_persistent", PCT_ADAPTER)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)

    assert adapter.Connection.force_persistence is True
    expected_docs = proxmox_pct_remote.DOCUMENTATION.replace(
        "name: proxmox_pct_remote", "name: pct_remote_persistent", 1
    )
    expected_docs = expected_docs.replace(
        'description: "Toggles the use of persistence for connections."',
        'description: "This adapter always uses persistence; this option cannot disable it."',
        1,
    )
    assert adapter.DOCUMENTATION == expected_docs

    context = PlayContext()
    context.connection = "pct_remote_persistent"
    connection = connection_loader.get("pct_remote_persistent", context, new_stdin=None)
    assert connection.force_persistence is True
    assert connection.get_option("pty") is False
    assert connection.is_pipelining_enabled() is False

    ssh_context = PlayContext()
    ssh_context.connection = "ssh"
    ssh_connection = connection_loader.get("ssh", ssh_context, new_stdin=None)
    assert ssh_connection.is_pipelining_enabled() is True


def test_pct_persistence_is_scoped_by_the_real_inventory_connection_expression():
    loader = yaml.safe_load((ROOT / "inventory/load_tofu/add_lxc_hosts.yml").read_text())
    add_host = next(task["ansible.builtin.add_host"] for task in loader
                    if "ansible.builtin.add_host" in task)
    connection = Template(add_host["ansible_connection"])

    cases = (
        (False, ["homarr"], "pct_remote_persistent"),
        (True, ["homarr"], "ssh"),
        (False, [], "community.proxmox.proxmox_pct_remote"),
    )
    for ssh_ready, tags, expected in cases:
        rendered = connection.render(_ssh_ready=ssh_ready, item={"value": {"tags": tags}})
        assert rendered.strip() == expected
