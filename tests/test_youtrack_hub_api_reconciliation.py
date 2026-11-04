"""Static contract checks for YouTrack Hub API reconciliation."""

from copy import deepcopy
from pathlib import Path

import yaml
from jinja2.nativetypes import NativeEnvironment


ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "roles/youtrack/tasks"
DEFAULTS = yaml.safe_load(
    (ROOT / "roles/youtrack/defaults/main.yml").read_text(encoding="utf-8")
)
ENV = NativeEnvironment()
ENV.filters["combine"] = lambda first, second: {**first, **second}


def _tasks():
    for path in sorted(TASKS_DIR.glob("*.yml")):
        tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for task in tasks:
            yield task


def _task(name):
    return next(task for task in _tasks() if task.get("name") == name)


def _render(value, context):
    if isinstance(value, dict):
        return {key: _render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    if isinstance(value, str) and "{{" in value:
        return ENV.from_string(value).render(context)
    return value


def _condition_matches(when, context):
    expressions = when if isinstance(when, list) else [when]
    return all(
        ENV.from_string("{{ " + expression + " }}").render(context)
        for expression in expressions
    )


def _desired_module_fields():
    return _render(
        DEFAULTS["youtrack_hub_auth_module_fields"],
        {"youtrack_hub_provider_url": "https://authelia.example.test"},
    )


def _module_drift(module, desired):
    expression = _task("Detect drift in the YouTrack Hub authentication module")[
        "ansible.builtin.set_fact"
    ]["youtrack_hub_auth_module_drift"]
    return ENV.from_string(expression).render(
        {
            "youtrack_hub_auth_module": module,
            "youtrack_hub_auth_module_fields": desired,
        }
    )


def _identity_check(user, link):
    task = _task("Determine whether each OAuth identity link already exists")
    context = {
        "youtrack_hub_identity_user_read": {
            "json": [user],
            "item": link,
        },
        "youtrack_hub_auth_module_name": "Authelia",
    }
    for name, expression in task.get("vars", {}).items():
        context[name] = _render(expression, context)
    facts = {
        name: _render(expression, context)
        for name, expression in task["ansible.builtin.set_fact"].items()
    }
    return facts


def test_matching_auth_module_fields_do_not_trigger_a_write():
    desired = _desired_module_fields()
    module = {"id": "module-1", **deepcopy(desired)}

    drift = _module_drift(module, desired)
    context = {"youtrack_hub_auth_module_drift": drift, "ansible_check_mode": False}

    assert drift is False
    assert not _condition_matches(
        _task("Update the existing YouTrack Hub authentication module")["when"],
        context,
    )


def test_scope_with_groups_triggers_an_update_with_the_required_type():
    desired = _desired_module_fields()
    module = {
        "id": "module-1",
        **deepcopy(desired),
        "scope": "openid profile email groups",
    }
    drift = _module_drift(module, desired)
    context = {
        "youtrack_hub_auth_module_drift": drift,
        "ansible_check_mode": False,
        "youtrack_hub_auth_module_fields": desired,
    }

    assert drift is True
    assert _condition_matches(
        _task("Update the existing YouTrack Hub authentication module")["when"],
        context,
    )
    body = _render(
        _task("Update the existing YouTrack Hub authentication module")[
            "ansible.builtin.uri"
        ]["body"],
        context,
    )
    assert body["type"] == "Oauth2authmoduleJSON"
    assert body["scope"] == "openid profile email"
    assert set(body) == set(desired) | {"type"}


def test_existing_identity_link_does_not_trigger_a_write():
    link = {"login": "operator", "identifier": "operator"}
    user = {
        "id": "user-1",
        "login": "operator",
        "details": [
            {
                "$type": "Oauth2detailsJSON",
                "authModule": {"name": "Authelia"},
                "identifier": "operator",
            }
        ],
    }
    facts = _identity_check(user, link)
    context = {
        "youtrack_hub_identity_link_check": {
            "ansible_facts": facts,
            "item": {"item": link},
        },
        "ansible_check_mode": False,
    }

    assert facts["youtrack_hub_identity_link_present"] is True
    assert not _condition_matches(
        _task("Create missing YouTrack Hub OAuth identity links")["when"],
        context,
    )


def test_missing_identity_link_posts_the_expected_body():
    link = {"login": "operator", "identifier": "operator"}
    user = {"id": "user-1", "login": "operator", "details": []}
    facts = _identity_check(user, link)
    context = {
        "youtrack_hub_identity_link_check": {
            "ansible_facts": facts,
            "item": {"item": link},
        },
        "youtrack_hub_auth_module": {"id": "module-1"},
        "ansible_check_mode": False,
    }
    task = _task("Create missing YouTrack Hub OAuth identity links")

    assert facts["youtrack_hub_identity_link_present"] is False
    assert _condition_matches(task["when"], context)
    body = _render(task["ansible.builtin.uri"]["body"], context)
    assert body == {
        "type": "Oauth2detailsJSON",
        "authModule": {"id": "module-1"},
        "identifier": "operator",
    }


def test_every_task_that_references_the_admin_token_is_hidden_from_logs():
    for task in _tasks():
        if "youtrack_hub_admin_token" in yaml.safe_dump(task):
            assert task.get("no_log") is True, task.get("name", "unnamed token task")


def test_every_get_runs_in_check_mode_without_reporting_a_change():
    for task in _tasks():
        uri = task.get("ansible.builtin.uri")
        if isinstance(uri, dict) and uri.get("method", "GET").upper() == "GET":
            assert task.get("check_mode") is False, task.get("name", "unnamed GET")
            assert task.get("changed_when") is False, task.get("name", "unnamed GET")


def test_identity_links_accept_the_api_type_field_alias():
    link = {"login": "operator", "identifier": "operator"}
    user = {
        "id": "user-1",
        "login": "operator",
        "details": [
            {
                "type": "Oauth2detailsJSON",
                "authModule": {"name": "Authelia"},
                "identifier": "operator",
            }
        ],
    }

    assert _identity_check(user, link)["youtrack_hub_identity_link_present"] is True
