"""Contracts for Hatchet worker token publishing and renewal."""

import time

import yaml

from test_hatchet_gpu_fill_worker import (
    DEFAULTS,
    ROOT,
    TOKEN_READ_TASKS,
    TOKEN_TASKS,
    _render_task_expression,
    _signed_token,
)


def test_token_renewal_decision_renders_absent_far_and_near_expiry():
    decision = next(
        task for task in TOKEN_TASKS
        if task["name"] == "Decide whether the Hatchet worker token needs minting"
    )
    expression = decision["ansible.builtin.set_fact"]["hatchet_docker_worker_token_needs_mint"]
    padding = next(
        task
        for task in TOKEN_TASKS
        if task["name"] == "Pad the existing Hatchet token payload for base64 decoding"
    )
    decode = next(task for task in TOKEN_TASKS if task["name"] == "Decode the existing Hatchet token expiry")
    decode_expression = decode["ansible.builtin.set_fact"]["hatchet_docker_worker_token_exp"]
    padding_expression = padding["ansible.builtin.set_fact"]["hatchet_docker_worker_token_payload_padded"]
    renew_days = DEFAULTS["hatchet_docker_worker_token_renew_days"]

    def needs_mint(token):
        expiry = 0
        if len(token.split(".")) == 3:
            padded_payload = _render_task_expression(
                padding_expression,
                {"hatchet_docker_worker_token_payload_segment": token.split(".")[1]},
            )
            expiry = _render_task_expression(
                decode_expression,
                {"hatchet_docker_worker_token_payload_padded": padded_payload},
            )
        return _render_task_expression(
            expression,
            {
                "hatchet_docker_worker_token_current": token,
                "hatchet_docker_worker_token_renew_days": renew_days,
                "hatchet_docker_worker_token_exp": expiry,
            },
        )

    now = int(time.time())
    assert needs_mint("") is True
    assert needs_mint(_signed_token(now + (renew_days + 5) * 86400)) is False
    assert needs_mint(_signed_token(now + (renew_days - 5) * 86400)) is True


def test_token_publisher_is_opt_in_tagged_and_reuses_shared_kv_seed_role():
    main_tasks = yaml.safe_load((ROOT / "roles/hatchet_docker/tasks/main.yml").read_text())
    leaf_read_include = next(task for task in main_tasks if "worker_token_read.yml" in str(task))
    assert set(leaf_read_include["tags"]) == {"hatchet_docker", "hatchet_worker_token"}
    publish_include = next(task for task in main_tasks if "worker_token_publish.yml" in str(task))
    assert publish_include["when"] == "hatchet_docker_worker_token_publish | bool"
    assert "hatchet_worker_token" in publish_include["tags"]
    assert DEFAULTS["hatchet_docker_worker_token_publish"] is False
    site = (ROOT / "playbooks/site/03-notifications-and-core-apps.yml").read_text()
    assert "- hatchet_worker_token" in site

    gate = next(task for task in TOKEN_TASKS if "human-unlocked publisher token" in task["name"])
    assert gate["ansible.builtin.assert"]["that"] == [
        "lookup('env', 'HATCHET_TOKEN_PUBLISHER_BAO_TOKEN') | length > 0"
    ]
    assert "HATCHET_TOKEN_PUBLISHER_BAO_TOKEN" in gate["ansible.builtin.assert"]["fail_msg"]
    mint = next(task for task in TOKEN_TASKS if task["name"] == "Mint the Hatchet GPU fill worker token")
    assert mint["run_once"] is True
    assert mint["no_log"] is True
    assert mint["community.docker.docker_container"]["image"] == "{{ hatchet_docker_admin_image }}"
    assert mint["community.docker.docker_container"]["command"] == [
        "token",
        "create",
        "--tenant-id",
        "{{ hatchet_docker_tenant_id }}",
        "--name",
        "gpu-fill-worker",
        "--expiresIn",
        "{{ hatchet_docker_worker_token_expires_in }}",
    ]

    publisher = next(
        task
        for task in TOKEN_TASKS
        if task["name"] == "Publish the Hatchet worker token to the apps secret"
    )
    include = publisher["block"][0]
    assert include["ansible.builtin.include_role"]["name"] == "dryvist.homelab.openbao_secrets"
    assert include["ansible.builtin.include_role"]["tasks_from"] == "seed_generated.yml"
    assert include["vars"]["openbao_secrets_seed_path"] == "apps/hatchet/worker-token"
    assert include["vars"]["openbao_secrets_seed_check_capabilities"] is True
    assert include["vars"]["openbao_secrets_seed_token"] == (
        "{{ lookup('env', 'HATCHET_TOKEN_PUBLISHER_BAO_TOKEN') }}"
    )
    assert include["vars"]["openbao_secrets_seed_token"] != "{{ lookup('env', 'BAO_TOKEN') }}"

    leaf_read = next(task for task in TOKEN_READ_TASKS if task["name"] == "Read the Hatchet worker token from its OpenBao leaf")
    assert leaf_read["ansible.builtin.uri"]["url"].endswith(
        "/v1/secret/data/apps/hatchet/worker-token"
    )
    assert leaf_read["ansible.builtin.uri"]["headers"]["X-Vault-Token"] == (
        "{{ lookup('env', 'BAO_TOKEN') }}"
    )
    assert leaf_read["ansible.builtin.uri"]["ca_path"] == "{{ openbao_ca_path }}"
    assert leaf_read["ansible.builtin.uri"]["status_code"] == [200, 403, 404]
    assert leaf_read["no_log"] is True
    denied = next(task for task in TOKEN_READ_TASKS if "is denied" in task["name"])
    assert "status | int == 403" in denied["when"]
    assert "HTTP 403" in denied["ansible.builtin.fail"]["msg"]

    current = next(task for task in TOKEN_TASKS if task["name"].startswith("Load the current"))
    assert "hostvars['localhost'].hatchet_docker_worker_token_current" in current[
        "ansible.builtin.set_fact"]["hatchet_docker_worker_token_current"]

    main_tasks = yaml.safe_load((ROOT / "roles/hatchet_docker/tasks/main.yml").read_text())
    read_import = next(task for task in main_tasks if task.get("ansible.builtin.import_tasks") == "worker_token_read.yml")
    assert read_import["when"] == (
        "hatchet_docker_worker_enabled | bool or hatchet_docker_worker_token_publish | bool"
    )

    worker_template = (ROOT / "roles/hatchet_docker/templates/docker-compose.yml.j2").read_text()
    assert "hostvars['localhost'].hatchet_docker_worker_token_current" in worker_template
    assert "secret/apps/hatchet/worker-token" in worker_template
