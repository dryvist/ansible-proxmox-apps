"""Review runner slots mount nothing from the host; pooled slots keep their mounts."""

from pathlib import Path

import yaml

from app_agent_helpers import _render


ROLE = Path(__file__).resolve().parents[1] / "roles" / "github_runner"
UNIT = (ROLE / "templates" / "github-runner@.service.j2").read_text(encoding="utf-8")
MOUNTS = (ROLE / "templates" / "runner-mounts.env.j2").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
SOCKET = "/var/run/docker.sock"


def _vars(**extra):
    return {**DEFAULTS, "ansible_managed": "test fixture", "github_runner_docker_gid": "990",
            "github_runner_image": "runner:test", "github_runner_container_user": "1000:1000", **extra}


def _mounts(slot, review_slots, **extra):
    rendered = _render(MOUNTS, _vars(github_runner_slot=slot, github_runner_review_slots=review_slots, **extra))
    return next(line for line in rendered.splitlines() if line.startswith("RUNNER_HOST_MOUNTS="))


def _tasks(name):
    return yaml.safe_load((ROLE / "tasks" / name).read_text(encoding="utf-8"))


def test_review_slots_mount_nothing_from_the_host():
    assert _mounts(1, 3) == "RUNNER_HOST_MOUNTS="
    assert _mounts(3, 3) == "RUNNER_HOST_MOUNTS="
    assert _mounts(2, 2, github_runner_unit_diag_dir="/diag/review-org-%i") == "RUNNER_HOST_MOUNTS="


def test_pooled_and_heavy_slots_keep_their_per_slot_mounts_and_the_socket():
    pooled = _mounts(4, 3)
    assert f"--volume {DEFAULTS['github_runner_diag_host_dir']}/4:/actions-runner/_diag" in pooled
    assert f"--volume {DEFAULTS['github_runner_tool_cache_host_dir']}/4:" in pooled
    assert f"--group-add 990 --volume {SOCKET}:{SOCKET}" in pooled
    heavy = _mounts(1, 0, github_runner_unit_diag_dir="/diag/heavy-%i", github_runner_unit_tool_cache_dir="/cache/heavy-%i")
    assert "--volume /diag/heavy-1:/actions-runner/_diag --volume /cache/heavy-1:" in heavy


def test_the_rendered_review_pool_unit_names_no_host_mount_and_reads_its_slot_file():
    unit = _render(UNIT, _vars(
        github_runner_container_prefix="github-runner-review-example",
        github_runner_name_prefix="review-example",
        github_runner_unit_env_file="/etc/github-runner/runner.env-review-example",
        github_runner_unit_diag_dir="/diag/review-example-%i",
        github_runner_unit_tool_cache_dir="/cache/review-example-%i",
    ))
    assert SOCKET not in unit
    assert "--group-add" not in unit
    assert "_diag \\" not in unit
    assert "EnvironmentFile=/etc/github-runner/runner.env-review-example-%i.mounts" in unit
    assert "    $RUNNER_HOST_MOUNTS \\" in unit


def test_every_pool_renders_the_mounts_file_the_unit_reads():
    wiring = {
        "main.yml": "{{ github_runner_env_file }}-{{ github_runner_slot }}.mounts",
        "deploy_heavy_pool.yml": "{{ github_runner_env_file }}-heavy-{{ github_runner_heavy_slot }}.mounts",
        "deploy_review_pool.yml": (
            "{{ github_runner_env_file }}-review-{{ github_runner_review_pool.org }}-{{ github_runner_review_slot }}.mounts"
        ),
    }
    for file, dest in wiring.items():
        renders = [t for t in _tasks(file) if t.get("ansible.builtin.template", {}).get("src") == "runner-mounts.env.j2"]
        assert [t["ansible.builtin.template"]["dest"] for t in renders] == [dest], file
    heavy = {t["name"]: t for t in _tasks("deploy_heavy_pool.yml")}
    unit_vars = heavy["Deploy the heavy runner systemd unit template"]["vars"]
    mount_vars = heavy["Deploy heavy runner host mounts files"]["vars"]
    for key in ("github_runner_unit_diag_dir", "github_runner_unit_tool_cache_dir"):
        assert mount_vars[key] == unit_vars[key]
