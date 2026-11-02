"""Kill test A safety contracts: derived target, unskippable restore, no token redirects."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/hatchet-killtest.yml"
TASKS = ROOT / "playbooks/tasks"
FILES = [PLAYBOOK] + sorted(TASKS.glob("hatchet_killtest_*.yml"))


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _tasks(node):
    """Every task dict, descending into block/rescue/always."""
    for task in node or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key))


def _task_fields(task):
    return str({key: value for key, value in task.items() if key not in {"block", "rescue", "always"}})


def _all_tasks():
    for path in FILES:
        data = _load(path)
        plays = data if path == PLAYBOOK else [{"tasks": data}]
        for play in plays:
            yield from ((path.name, task) for task in _tasks(play.get("tasks")))


def _play():
    return next(play for play in _load(PLAYBOOK) if play.get("name", "").startswith("Kill one Hatchet guest"))


def test_the_target_comes_from_the_sorted_tag_set_only():
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert "docker_ai_group" not in text
    derive = next(t for t in _play()["tasks"] if t["name"].startswith("Derive the guests"))
    assert "contains', 'hatchet-killtest'" in derive["ansible.builtin.set_fact"]["hatchet_killtest_guests"]
    assert derive["ansible.builtin.set_fact"]["hatchet_killtest_guests"].rstrip().endswith("| sort }}")
    assert "hatchet_killtest_tag" not in _play().get("vars", {})


def test_caller_overrides_are_refused_before_anything_runs():
    plays = _load(PLAYBOOK)
    assert plays[0]["name"].startswith("Refuse caller overrides")
    assert plays[1].get("import_playbook") == "../inventory/load_tofu.yml"
    gate = plays[0]["tasks"][0]
    assert gate["ansible.builtin.assert"]["that"] == "item not in hostvars[inventory_hostname]"
    required = {
        "tofu_data", "openbao_secrets_domains", "openbao_secrets_by_domain",
        "openbao_secrets_domain_groups", "openbao_secrets_active_groups",
        "hatchet_killtest_tag", "hatchet_killtest_action",
        "hatchet_killtest_budget_seconds", "hatchet_killtest_deadline_epoch",
        "hatchet_killtest_recovery_reserve",
    }
    existing_refusals = {
        "hatchet_killtest_guests", "hatchet_killtest_target", "hatchet_killtest_survivor",
        "hatchet_killtest_vmid", "hatchet_killtest_node", "hatchet_killtest_api",
        "hatchet_killtest_guest_api", "hatchet_killtest_ca", "hatchet_killtest_secret",
        "hatchet_killtest_auth", "hatchet_killtest_ready_port", "hatchet_killtest_probe_host",
        "hatchet_killtest_started", "hatchet_killtest_failed", "hatchet_killtest_restore_failed",
    }
    assert required | existing_refusals <= set(gate["loop"])
    assert "add_lxc_hosts_live_node" in gate["loop"]
    env_gate = next(task for task in plays[0]["tasks"] if "TOFU_INVENTORY_PATH" in str(task))
    assert "lookup('env', 'TOFU_INVENTORY_PATH') | length == 0" in env_gate["ansible.builtin.assert"]["that"]


def test_target_and_survivor_are_distinct_tagged_published_containers():
    check = next(t for t in _play()["tasks"] if t["name"].startswith("Require two distinct tagged guests"))
    conditions = " ".join(check["ansible.builtin.assert"]["that"])
    assert "hatchet_killtest_target in tofu_data.containers" in conditions
    assert "hatchet_killtest_survivor in tofu_data.containers" in conditions
    assert "hatchet_killtest_target].vmid" in conditions
    assert "hatchet_killtest_survivor].vmid" in conditions
    assert "!= tofu_data.containers[hatchet_killtest_survivor].vmid" in conditions
    assert conditions.count("'hatchet-killtest' in tofu_data.containers.get(") == 2


def test_api_host_is_derived_from_a_valid_node_role_and_exact_domain_suffix():
    check = next(t for t in _play()["tasks"] if t["name"].startswith("Require the target, the survivor"))
    conditions = " ".join(check["ansible.builtin.assert"]["that"])
    assert "is match('^[a-z0-9-]+$')" in conditions
    assert "hatchet_killtest_api.split('://')[1].split(':')[0]" in conditions
    assert ".endswith('.' ~ tofu_data.domain)" in conditions
    assert "hatchet_killtest_api is match('^https://[^/]+:8006/api2/json$')" in conditions


def test_every_task_referencing_the_token_or_ca_is_masked():
    secret_copy = next(
        task for _, task in _all_tasks()
        if "hatchet_killtest_secret" in str(task.get("ansible.builtin.set_fact", {}))
    )
    assert secret_copy.get("no_log") is True

    markers = (
        "openbao_secrets_domains", "openbao_secrets_by_domain", "hatchet_killtest_secret", "hatchet_killtest_auth",
        "hatchet_killtest_pve_token", "hatchet_killtest_pve_ca", "hatchet_killtest_ca",
        "Authorization",
    )
    for _, task in _all_tasks():
        if task["name"].startswith("Refuse caller-supplied"):
            continue
        if any(marker in _task_fields(task) for marker in markers):
            assert task.get("no_log") is True, task["name"]


def test_power_task_uses_only_the_literal_stop_endpoint():
    power = _load(TASKS / "hatchet_killtest_power.yml")
    request = next(t["ansible.builtin.uri"] for t in power if "ansible.builtin.uri" in t)
    assert request["url"] == "{{ hatchet_killtest_guest_api }}/status/stop"
    assert "hatchet_killtest_action" not in (TASKS / "hatchet_killtest_power.yml").read_text(encoding="utf-8")


def test_stopped_guest_alert_runs_in_restore_always_and_fails_afterward():
    phases = _load(TASKS / "hatchet_killtest_phases.yml")[0]
    assert phases["rescue"], "the restore always path must run when the kill phase fails"
    restore = phases["always"][0]
    rescue = restore["rescue"]
    alert = next(task for task in rescue if task["name"].startswith("Alert when"))
    request = alert["ansible.builtin.uri"]
    assert "hatchet_killtest_deadline_epoch" in str(alert["when"])
    assert "hatchet_killtest_started" in str(alert["when"])
    assert request["url"] == "https://ntfy.{{ ingress_domain }}/keystone"
    assert request["headers"] == {
        "Title": "hatchet killtest: guest left stopped", "Priority": "urgent", "Tags": "warning",
    }
    assert "{{ hatchet_killtest_target }}" in request["body"]
    assert all(name not in request["body"] for name in ("vmid", "container_ip", "hatchet_killtest_node"))
    assert alert["failed_when"] is False
    assert "ignore_errors" not in alert
    fail = next(task for task in rescue if task["name"].startswith("Fail loudly"))
    assert "hatchet_killtest_deadline_epoch" in str(fail["when"])
    assert "hatchet_killtest_back.status" in str(fail["when"])
    assert fail.get("ansible.builtin.fail")
    assert restore["always"][-1]["ansible.builtin.file"]["state"] == "absent"


def test_every_delegated_probe_ignores_unreachable():
    delegated = [(name, t) for name, t in _all_tasks() if "delegate_to" in t]
    assert len(delegated) >= 3
    for name, task in delegated:
        assert task.get("ignore_unreachable") is True, (name, task["name"])


def test_no_authenticated_request_follows_redirects():
    requests = [(name, t["ansible.builtin.uri"]) for name, t in _all_tasks() if "ansible.builtin.uri" in t]
    authed = [(name, uri) for name, uri in requests if "Authorization" in uri.get("headers", {})]
    assert len(authed) >= 4
    for name, uri in authed:
        assert uri["follow_redirects"] == "none", name
        assert uri["unredirected_headers"] == ["Authorization"], name


def test_restore_retries_and_always_removes_the_ca_file():
    phases = _load(TASKS / "hatchet_killtest_phases.yml")[0]
    restore = phases["always"][0]
    reconcile = next(task for task in restore["block"] if task["name"].startswith("Reconcile start"))
    assert reconcile["ansible.builtin.include_tasks"] == "hatchet_killtest_start.yml"
    assert reconcile["loop"] == "{{ range(1, 601) | list }}"
    assert "hatchet_killtest_deadline_epoch" in str(reconcile["when"])
    assert "hatchet_killtest_back.status" in str(reconcile["when"])
    assert restore["rescue"], "a failed restore must be recorded, not abort the always block"
    assert [t["ansible.builtin.file"]["state"] for t in restore["always"]] == ["absent"]


def test_ready_polls_fail_fast_one_include_per_poll():
    ready = _load(TASKS / "hatchet_killtest_ready.yml")
    include = next(task for task in ready if "ansible.builtin.include_tasks" in task)
    assert include["ansible.builtin.include_tasks"] == "hatchet_killtest_ready_poll.yml"
    assert "hatchet_killtest_deadline_epoch" in str(include["when"])


def test_operational_until_and_loop_tasks_check_the_deadline():
    for filename, task in _all_tasks():
        if task["name"].startswith("Refuse caller-supplied"):
            continue  # This static safety gate must run before the clock is initialized.
        if "until" in task or "loop" in task:
            assert "hatchet_killtest_deadline_epoch" in _task_fields(task), (filename, task["name"])


def test_deadline_reserve_and_worst_case_timing_are_bounded():
    plays = _load(PLAYBOOK)
    refusal = plays[0]["tasks"][0]["loop"]
    assert {"hatchet_killtest_deadline_epoch", "hatchet_killtest_recovery_reserve"} <= set(refusal)
    fixed = next(t["ansible.builtin.set_fact"] for t in plays[0]["tasks"]
                 if t["name"].startswith("Set the fixed kill-test"))
    timer = next(t["ansible.builtin.set_fact"] for t in plays[0]["tasks"]
                 if t["name"].startswith("Start the single end-to-end"))
    budget = int(fixed["hatchet_killtest_budget_seconds"])
    reserve = int(fixed["hatchet_killtest_recovery_reserve"])
    assert budget == 570
    assert reserve == 300
    assert "now(utc=True).timestamp()" in timer["hatchet_killtest_deadline_epoch"]
    assert "hatchet_killtest_budget_seconds" in timer["hatchet_killtest_deadline_epoch"]

    phases = _load(TASKS / "hatchet_killtest_phases.yml")[0]
    power = _load(TASKS / "hatchet_killtest_power.yml")
    ready_poll = _load(TASKS / "hatchet_killtest_ready_poll.yml")
    stop_post = next(t["ansible.builtin.uri"] for t in power
                     if t["name"] == "Send stop to the target guest")
    stop_poll = next(t for t in power if "until" in t)
    down = next(t for t in phases["block"] if t["name"].startswith("Probe the target until"))
    survivor = next(t for t in phases["block"] if t["name"].startswith("Require the survivor"))
    placement = next(t for t in _load(ROOT / "inventory/load_tofu/add_lxc_hosts.yml")
                     if t["name"] == "Read live container placement from the cluster")
    placement_timeout = int(placement["ansible.builtin.command"].split()[2])
    polls = int(survivor["vars"]["hatchet_killtest_ready_polls"])
    pause = int(survivor["vars"]["hatchet_killtest_ready_pause"])
    ready_uri = next(t["ansible.builtin.uri"] for t in ready_poll if "loop" in t)
    ready_timeout = int(ready_uri["timeout"])

    def retry_bound(task):
        uri = task["ansible.builtin.uri"]
        retries = int(task["retries"])
        return (retries + 1) * int(uri["timeout"]) + retries * int(task["delay"])

    initial_ready_seconds = 2 * ready_timeout  # The playbook asserts exactly two selected guests.
    survivor_seconds = polls * ready_timeout + (polls - 1) * pause
    kill_seconds = (
        initial_ready_seconds + int(stop_post["timeout"]) + retry_bound(stop_poll)
        + retry_bound(down) + survivor_seconds
    )
    assert kill_seconds == 250
    pre_restore_seconds = placement_timeout + kill_seconds
    assert pre_restore_seconds == 265
    assert pre_restore_seconds < budget - reserve

    alert = next(t["ansible.builtin.uri"] for t in phases["always"][0]["rescue"]
                 if t["name"].startswith("Alert when"))
    total_seconds = max(budget, pre_restore_seconds + reserve) + 1 + int(alert["timeout"])
    assert total_seconds == 576
    assert total_seconds < 600
    comment = (TASKS / "hatchet_killtest_phases.yml").read_text(encoding="utf-8")
    assert f"{pre_restore_seconds}s" in comment
    assert f"{total_seconds}s" in comment


def test_restore_reconciles_from_upid_and_readiness_inside_always():
    phases = _load(TASKS / "hatchet_killtest_phases.yml")[0]
    restore = phases["always"][0]
    reconcile = next(t for t in restore["block"] if t["name"].startswith("Reconcile start"))
    assert "hatchet_killtest_deadline_epoch" in str(reconcile["when"])
    assert "hatchet_killtest_back.status" in str(reconcile["when"])
    start_tasks = _load(TASKS / "hatchet_killtest_start.yml")
    post = next(t for t in start_tasks if t["name"].startswith("Send start"))
    poll = next(t for t in start_tasks if "until" in t)
    probe = next(t for t in start_tasks if t["name"].startswith("Probe the target"))
    assert "hatchet_killtest_upids" in str(post["when"])
    assert "hatchet_killtest_deadline_epoch" in str(poll["until"])
    assert "hatchet_killtest_deadline_epoch" in str(poll["when"])
    assert "stopped" in poll["until"]
    assert probe["ansible.builtin.uri"]["timeout"] == 3
    assert "hatchet_killtest_deadline_epoch" in str(probe["when"])
    assert any("already running" in str(t) for t in start_tasks)
    assert any(t["name"].startswith("Require the target confirmed running and ready")
               for t in restore["block"])
    assert restore["rescue"][-1]["ansible.builtin.fail"]


def test_kill_and_survivor_work_stops_before_the_recovery_reserve():
    phases = _load(TASKS / "hatchet_killtest_phases.yml")[0]
    assert "hatchet_killtest_recovery_reserve" in str(phases["block"][0]["ansible.builtin.assert"])
    down = next(t for t in phases["block"] if t["name"].startswith("Probe the target until"))
    assert "hatchet_killtest_recovery_reserve" in str(down["until"])
    ready = _load(TASKS / "hatchet_killtest_ready.yml")
    loop = next(t for t in ready if "loop" in t)
    assert "hatchet_killtest_recovery_reserve" in str(loop["when"])
