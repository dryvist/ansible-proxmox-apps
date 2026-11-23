"""A general extra-org pool runs the main pool's labels; review pools keep theirs."""

from pathlib import Path

import yaml

from app_agent_helpers import _render


ROLE = Path(__file__).resolve().parents[1] / "roles" / "github_runner"
ENV = (ROLE / "templates" / "runner.env.j2").read_text(encoding="utf-8")
MOUNTS = (ROLE / "templates" / "runner-mounts.env.j2").read_text(encoding="utf-8")
AGENT = (ROLE / "templates" / "openbao-agent-pools.hcl.j2").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
ORG = "example-other"


def _tasks(name):
    return yaml.safe_load((ROLE / "tasks" / name).read_text(encoding="utf-8"))


def _pool_env(kind, slot, replicas):
    """The env-file vars deploy_pool.yml passes for one pool slot."""
    return _render(ENV, {**DEFAULTS, "ansible_managed": "test fixture",
                         "github_runner_org": ORG, "github_runner_group": "Default",
                         "github_runner_bao_addr": "https://bao.example.invalid",
                         "github_runner_review_slots": replicas if kind == "review" else 0,
                         "github_runner_slot": slot,
                         "github_runner_labels_extra": ""})


def _select_task():
    return next(t for t in _tasks("pools.yml")
                if t.get("ansible.builtin.set_fact", {}).get("github_runner_active_pools"))


def test_an_extra_org_slot_registers_with_the_main_pool_labels():
    lines = [line for line in _pool_env("general", 1, 1).splitlines() if line]
    assert "LABELS=self-hosted,Linux,X64,proxmox" in lines
    assert "ORG_NAME=example-other" in lines
    assert "RUNNER_GROUP=Default" in lines
    assert not any(line.startswith("NO_DEFAULT_LABELS") for line in lines)


def test_an_extra_org_slot_keeps_the_host_mounts():
    rendered = _render(MOUNTS, {**DEFAULTS, "ansible_managed": "test fixture",
                                "github_runner_docker_gid": "990",
                                "github_runner_slot": 1, "github_runner_review_slots": 0,
                                "github_runner_unit_diag_dir":
                                    f"{DEFAULTS['github_runner_diag_host_dir']}/general-{ORG}-%i",
                                "github_runner_unit_tool_cache_dir":
                                    f"{DEFAULTS['github_runner_tool_cache_host_dir']}/general-{ORG}-%i"})
    mounts = next(line for line in rendered.splitlines() if line.startswith("RUNNER_HOST_MOUNTS="))
    assert "/var/run/docker.sock" in mounts
    assert f"general-{ORG}-1:/actions-runner/_diag" in mounts


def test_selection_tags_each_pool_with_its_kind_and_honors_zero_replicas():
    expression = _select_task()["ansible.builtin.set_fact"]["github_runner_active_pools"].strip()
    pools = _render(expression, {"github_runner_review_orgs": [{"org": "example-review"}],
                                 "github_runner_extra_orgs": [{"org": ORG}],
                                 "github_runner_replicas": "2"})
    assert pools == [{"kind": "review", "org": "example-review"},
                     {"kind": "general", "org": ORG}]
    assert _render(expression, {"github_runner_review_orgs": [],
                                "github_runner_extra_orgs": [{"org": ORG}],
                                "github_runner_replicas": "0"}) == []


def test_the_general_pool_wiring_matches_across_unit_env_and_token_files():
    deploy = _tasks("deploy_pool.yml")
    env = next(t for t in deploy if t.get("name") == "Deploy pool runner environment files")
    unit = next(t for t in deploy
                if t.get("name") == "Deploy the pool runner systemd unit template")
    prefix = ("{{ github_runner_env_file }}-{{ github_runner_pool.kind }}"
              "-{{ github_runner_pool.org }}")
    assert env["ansible.builtin.template"]["dest"] == prefix + "-{{ github_runner_pool_slot }}"
    mounts = next(t for t in deploy if t.get("name") == "Deploy pool runner host mounts files")
    assert mounts["ansible.builtin.template"]["dest"] == env["ansible.builtin.template"]["dest"] + ".mounts"
    unit_vars = unit["vars"]
    assert unit_vars["github_runner_unit_env_file"] == prefix
    assert unit_vars["github_runner_unit_diag_dir"] == (
        "{{ github_runner_diag_host_dir }}/{{ github_runner_pool.kind }}-{{ github_runner_pool.org }}-%i")
    token_file = " ".join(unit_vars["github_runner_unit_token_env_file"].split())
    assert "'/access-token-'" in token_file and "github_runner_pool.org" in token_file
    # The agent template writes the same per-org file the unit waits on; the
    # template itself is kind-agnostic (rendered only by the CI harness,
    # tests/template_render/verify/github_runner_openbao_agent.yml, because it
    # {% include %}s its sibling).
    assert 'access-token-{{ github_runner_pool.org }}.env"' in AGENT
    assert "org_name={% endraw %}{{ github_runner_pool.org }}" in AGENT


def test_each_selected_pool_keeps_its_callers_keys_and_gains_its_kind():
    expression = _select_task()["ansible.builtin.set_fact"]["github_runner_active_pools"].strip()
    pools = _render(expression, {"github_runner_review_orgs": [{"org": "example-review",
                                                                "replicas": 3}],
                                 "github_runner_extra_orgs": [{"org": ORG, "group": "Other"}],
                                 "github_runner_replicas": "1"})
    assert pools[0]["replicas"] == 3
    assert pools[1] == {"org": ORG, "group": "Other", "kind": "general"}
