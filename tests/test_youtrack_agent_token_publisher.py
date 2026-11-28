"""The YouTrack agent-token publisher is gated, uses the collection role and hides tokens."""

from app_agent_helpers import _render, _task, _task_tree, _yaml


def test_youtrack_agent_token_publisher_is_gated_and_uses_the_collection_contract():
    defaults = _yaml("roles/youtrack/defaults/main.yml")
    assert defaults["youtrack_agent_token_publish_openbao"] is False
    play = _yaml("playbooks/site/04e-youtrack.yml")[0]
    assert play["vars"]["youtrack_agent_token_publish_openbao"] is True
    assert defaults["youtrack_agent_write_login"] == "svc-ai"
    assert defaults["youtrack_agent_write_token_name"] == "agent-tier-youtrack-write"
    assert defaults["youtrack_agent_write_token_remint"] is False

    main = _yaml("roles/youtrack/tasks/main.yml")
    entry = _task(main, "Publish the YouTrack agent token to OpenBao")
    assert entry["when"] == "youtrack_agent_token_publish_openbao | bool"
    assert entry["ansible.builtin.include_tasks"]["apply"]["no_log"] is True
    assert entry["no_log"] is True

    tasks = _yaml("roles/youtrack/tasks/publish_agent_token.yml")
    mint = _task(tasks, "Ensure the YouTrack agent token exists for its service user")
    assert mint["ansible.builtin.include_role"]["name"] == "jpe_ansible.youtrack.service_tokens"
    assert mint["vars"]["youtrack_url"] == "{{ youtrack_hub_base_url }}"
    assert mint["vars"]["youtrack_api_key"] == "{{ youtrack_hub_admin_token }}"
    assert mint["vars"]["service_tokens_declared"] == [
        {"login": "{{ youtrack_agent_write_login }}", "name": "{{ youtrack_agent_write_token_name }}"}
    ]
    assert "youtrack_agent_write_token_remint | bool" in mint["vars"]["service_tokens_remint"]
    assert mint["no_log"] is True
    assert mint["ansible.builtin.include_role"]["apply"]["no_log"] is True

    openbao_assert = _task(tasks, "Require OpenBao write credentials for YouTrack publication")
    assert "youtrack_openbao_addr | length > 0" in openbao_assert["ansible.builtin.assert"]["that"]
    assert "youtrack_openbao_token | length > 0" in openbao_assert["ansible.builtin.assert"]["that"]
    assert openbao_assert["no_log"] is True

    token_publish = _task(tasks, "Publish a newly minted YouTrack agent token through the shared OpenBao publisher")
    token_publish_vars = token_publish["vars"]
    assert token_publish["ansible.builtin.include_tasks"]["file"].endswith("/zammad/tasks/publish_mcp.yml")
    assert token_publish_vars["zammad_token_openbao_mount"] == "{{ youtrack_agent_write_openbao_mount }}"
    assert token_publish_vars["zammad_token_openbao_path"] == "{{ youtrack_agent_write_openbao_path }}"
    assert token_publish_vars["zammad_token_openbao_key"] == "{{ youtrack_agent_write_openbao_field }}"
    assert token_publish_vars["zammad_publish_url"] is False
    assert token_publish_vars["zammad_publish_token"] == (
        "{{ service_tokens_minted[youtrack_agent_write_token_name] }}"
    )
    assert token_publish["when"] == (
        "youtrack_agent_write_token_name in (service_tokens_minted | default({}, true))"
    )
    assert token_publish["no_log"] is True
    assert token_publish["ansible.builtin.include_tasks"]["apply"]["no_log"] is True

    minted = {"agent-tier-youtrack-write": "fixture-token"}
    condition = "{{ " + token_publish["when"] + " }}"
    assert _render(
        condition,
        {"youtrack_agent_write_token_name": "agent-tier-youtrack-write", "service_tokens_minted": minted},
    )
    assert not _render(
        condition,
        {"youtrack_agent_write_token_name": "agent-tier-youtrack-write", "service_tokens_minted": {}},
    )


def test_youtrack_existing_token_leaf_requires_remint_only_when_empty():
    tasks = _yaml("roles/youtrack/tasks/publish_agent_token.yml")
    requirement = _task(tasks, "Require an existing YouTrack token value or a newly minted token")
    expression = "{{ " + requirement["ansible.builtin.assert"]["that"][0] + " }}"
    variables = {
        "youtrack_agent_write_token_name": "agent-tier-youtrack-write",
        "youtrack_agent_write_openbao_field": "YOUTRACK_AGENT_WRITE_TOKEN",
        "service_tokens_minted": {},
        "youtrack_agent_write_openbao_read": {
            "json": {"data": {"data": {"YOUTRACK_AGENT_WRITE_TOKEN": "present"}}}
        },
    }
    assert _render(expression, variables)
    variables["youtrack_agent_write_openbao_read"] = {"json": {"data": {"data": {}}}}
    assert not _render(expression, variables)
    fail_msg = requirement["ansible.builtin.assert"]["fail_msg"]
    assert "youtrack_agent_write_token_remint=true" in fail_msg
    assert "service_tokens_remint" in fail_msg
    assert requirement["no_log"] is True


def test_youtrack_publisher_writes_only_the_tier_leaf_and_hides_tokens():
    defaults = _yaml("roles/youtrack/defaults/main.yml")
    assert defaults["youtrack_agent_write_openbao_mount"] == "agent-tier"
    assert defaults["youtrack_agent_write_openbao_path"] == "youtrack-write"
    assert defaults["youtrack_agent_write_openbao_field"] == "YOUTRACK_AGENT_WRITE_TOKEN"
    # The router derives the endpoint, so no address is stored anywhere.
    assert not [key for key in defaults if key.startswith("youtrack_mcp_")]

    tasks = _yaml("roles/youtrack/tasks/publish_agent_token.yml")
    assert "MCP_URL" not in str(tasks)

    for task in _task_tree(tasks):
        serialized = str(task)
        if any(
            secret in serialized
            for secret in (
                "youtrack_hub_admin_token",
                "service_tokens_minted",
                "youtrack_openbao_token",
                "zammad_publish_token",
            )
        ):
            assert task.get("no_log") is True, task.get("name")
