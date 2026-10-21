"""Check-mode guards for unarchive tasks with simulated inputs."""

import pytest
import yaml

from health_probes_check_mode_support import REPO, _tasks_in


GUARDED_UNARCHIVES = (
    ("roles/unpoller/tasks/main.yml", "Unpack the unpoller release", (
        ("Copy the staged release tarball to the guest", "unpoller_release_copy"),
        ("Create the versioned unpack directory", "unpoller_unpack_directory"),
    )),
    ("roles/agent_sandbox/tasks/main/deploy.yml", "Install pack pipeline conf as a worker-level pipeline", (
        ("Create Cribl Edge pipeline directories", "agent_sandbox_cribl_pipeline_directories"),
    )),
    ("roles/cribl_stream/tasks/main.yml", "Extract Cribl Stream tarball", (
        ("Download Cribl Stream tarball", "cribl_stream_install_download"),
    )),
    ("roles/cribl_stream/tasks/upgrade.yml", "Extract the new version over the existing install (local/ preserved)", (
        ("Download the pinned Cribl Stream tarball (checksum-verified)", "cribl_stream_upgrade_download"),
    )),
    ("roles/cribl_stream/tasks/pipelines.yml", "Ship and extract every pipeline directory and config in one transfer", (
        ("Ensure the pipeline configs parent directory exists", "cribl_stream_pipelines_parent_directory"),
    )),
    ("roles/github_runner_arc/tasks/k3s.yml", "Extract the Helm binary", (
        ("Download the Helm release archive", "github_runner_arc_helm_archive"),
    )),
    ("roles/glance/tasks/main.yml", "Unpack the verified archive", (
        ("Create the unpack staging directory", "glance_unpack_directory"),
        ("Fetch the pinned glance release (checksum-verified)", "glance_fetch"),
    )),
    ("roles/grafana_stack/tasks/main.yml", "Deploy provisioned dashboards from the pinned grafana-dashboards release", (
        ("Create grafana stack directories", "grafana_stack_directories"),
    )),
    ("roles/idrac_kvm_docker/tasks/main.yml", "Unpack AVCT client into build context (creates app/)", (
        ("Fetch AVCT client artifact into build context", "idrac_kvm_docker_avct_archive"),
    )),
    ("roles/ntfy_docker/tasks/slack_fanout.yml", "Extract the ntfy-to-slack binary", (
        ("Download the ntfy-to-slack release tarball", "ntfy_docker_to_slack_archive"),
    )),
    ("roles/postgres/tasks/main/patroni_etcd.yml", "Extract the etcd archive on the target", (
        ("Copy the etcd archive to the target", "postgres_ha_etcd_archive_copy"),
    )),
    ("roles/status_stack/tasks/autokuma_static_monitors.yml", "Ship and extract the AutoKuma monitor set in one transfer", (
        ("Ensure the AutoKuma static-monitors directory exists", "status_stack_autokuma_directory"),
    )),
    ("roles/technitium_install/tasks/deploy_app.yml", "Extract the Technitium app distribution", (
        ("Ensure the Technitium app directory exists", "technitium_install_app_directory"),
    )),
    ("roles/technitium_install/tasks/upgrade.yml", "Restore the pre-upgrade Technitium app and data", (
        ("Back up the existing Technitium app build and data for rollback", "technitium_install_upgrade_backup"),
    )),
    ("roles/wall/tasks/main.yml", "Unpack the verified archives", (
        ("Create the wall directories", "wall_directories"),
    )),
)


@pytest.mark.parametrize(("relative_path", "unarchive_name", "producers"), GUARDED_UNARCHIVES)
def test_unarchive_skips_only_when_check_mode_simulates_a_required_input(
    relative_path, unarchive_name, producers
):
    tasks = {
        task["name"]: task
        for task in _tasks_in(yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8")))
    }
    unarchive = tasks[unarchive_name]
    condition = unarchive.get("when", "")
    if isinstance(condition, list):
        condition = "\n".join(map(str, condition))

    assert "ansible_check_mode" in condition
    if relative_path == "roles/wall/tasks/main.yml":
        assert "item.changed" in condition
        assert tasks["Fetch the pinned release assets (checksum-verified)"]["register"] == "wall_fetch"
    if relative_path == "roles/technitium_install/tasks/deploy_app.yml":
        download_tasks = _tasks_in(
            yaml.safe_load((REPO / "roles/technitium_install/tasks/download_app.yml").read_text(encoding="utf-8"))
        )
        download = next(task for task in download_tasks if task["name"] == "Download the Technitium app from the mirror (checksum-pinned)")
        assert download["register"] == "technitium_install_app_download"
        assert "technitium_install_app_download" in condition
    for producer_name, result_name in producers:
        assert tasks[producer_name]["register"] == result_name
        assert result_name in condition
