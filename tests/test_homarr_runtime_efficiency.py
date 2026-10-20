"""Keep Homarr's slow module loops and duplicate restarts out of the converge."""

from pathlib import Path

import yaml
from jinja2 import Template


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/homarr"


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


def test_pct_transport_uses_upstream_plugin_for_homarr():
    loader = yaml.safe_load((ROOT / "inventory/load_tofu/add_lxc_hosts.yml").read_text())
    add_host = next(task["ansible.builtin.add_host"] for task in loader
                    if "ansible.builtin.add_host" in task)
    connection = Template(add_host["ansible_connection"])

    cases = (
        (False, ["homarr"], "community.proxmox.proxmox_pct_remote"),
        (True, ["homarr"], "ssh"),
        (False, [], "community.proxmox.proxmox_pct_remote"),
    )
    for ssh_ready, tags, expected_connection in cases:
        context = {"_ssh_ready": ssh_ready, "item": {"value": {"tags": tags}}}
        assert connection.render(**context).strip() == expected_connection
    assert not (ROOT / "plugins/connection/pct_remote_persistent.py").exists()
