"""The ai-jobs publisher: one ntfy user with write-only access to one topic, its
single access token, and the token published to the open-llm bucket.

Everything is gated by ntfy_docker_ai_jobs_enabled (default off): with it off
the rendered server config and compose file are byte-identical to the ones
without the feature, and no stage runs. The publish is a check-and-set merge,
so a sibling writer's fields survive and a racing writer makes the write fail.

These render the REAL expressions and templates, never a reimplementation.
"""

from pathlib import Path

import jinja2
import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
NTFY = ROOT / "roles/ntfy_docker"
USER = "ai-jobs-publisher"
TOPIC = "ai-jobs"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _defaults() -> dict:
    return _yaml(NTFY / "defaults/main.yml")


def _tasks() -> list[dict]:
    return _yaml(NTFY / "tasks/ai_jobs_publisher.yml")


def _task(name: str, tasks: list[dict] | None = None) -> dict:
    for task in tasks if tasks is not None else _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found")


def _render(expr, variables: dict):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(expr))


def _holds(conditions, variables: dict) -> bool:
    if not isinstance(conditions, list):
        conditions = [conditions]
    return all(bool(_render("{{ " + c + " }}", variables)) for c in conditions)


def _vars(**extra) -> dict:
    base = {
        "ntfy_docker_container_name": "ntfy",
        "ntfy_docker_ai_jobs_user": USER,
        "ntfy_docker_ai_jobs_topic": TOPIC,
        "ntfy_docker_ai_jobs_token_label": "ai-jobs-dispatcher",
    }
    base.update(extra)
    return base


def _template(name: str, **variables) -> str:
    env = jinja2.Environment(trim_blocks=True, undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda value: str(value).lower() in {"1", "true", "yes", "on"}
    defaults = {
        "ntfy_docker_base_url": "https://ntfy.example.test",
        "ntfy_docker_cache_duration": "12h",
        "ntfy_docker_attachment_cache_dir": "/var/cache/ntfy/attachments",
        "ntfy_docker_auth_file": "/var/lib/ntfy/user.db",
        "ntfy_docker_auth_dir": "/opt/ntfy/auth",
        "ntfy_docker_data_dir": "/opt/ntfy",
        "ntfy_docker_image": "binwiederhier/ntfy:v0",
        "ntfy_docker_container_name": "ntfy",
        "ntfy_docker_http_port": 8080,
    }
    defaults.update(variables)
    source = (NTFY / "templates" / name).read_text(encoding="utf-8")
    return env.from_string(source).render(**defaults)


# --- gate: off means no change -------------------------------------------------


def test_the_gate_defaults_off():
    assert _defaults()["ntfy_docker_ai_jobs_enabled"] is False


def test_the_ntfy_hosts_turn_the_gate_on():
    group_vars = _yaml(ROOT / "inventory/group_vars/ntfy_group.yml")
    assert group_vars["ntfy_docker_ai_jobs_enabled"] is True


def test_server_config_is_unchanged_with_the_gate_off():
    assert _template("server.yml.j2", ntfy_docker_ai_jobs_enabled=False) == (
        'base-url: "https://ntfy.example.test"\n'
        'listen-http: ":80"\n'
        'cache-file: "/var/cache/ntfy/cache.db"\n'
        'cache-duration: "12h"\n'
        'attachment-cache-dir: "/var/cache/ntfy/attachments"\n'
    )


def test_compose_mounts_no_auth_volume_with_the_gate_off():
    rendered = _template("docker-compose.yml.j2", ntfy_docker_ai_jobs_enabled=False)
    assert "/var/lib/ntfy" not in rendered
    assert "auth" not in rendered


def test_gate_on_adds_only_the_auth_file_and_its_volume():
    off = _template("server.yml.j2", ntfy_docker_ai_jobs_enabled=False)
    on = _template("server.yml.j2", ntfy_docker_ai_jobs_enabled=True)
    assert on == off + 'auth-file: "/var/lib/ntfy/user.db"\n'
    compose = _template("docker-compose.yml.j2", ntfy_docker_ai_jobs_enabled=True)
    assert "      - /opt/ntfy/auth:/var/lib/ntfy\n" in compose


def test_default_access_is_never_narrowed_by_the_config():
    # A deny default would cut every anonymous publisher and subscriber.
    rendered = _template("server.yml.j2", ntfy_docker_ai_jobs_enabled=True)
    assert "auth-default-access" not in rendered


def test_the_stage_and_the_auth_directory_wait_on_the_gate():
    main = _yaml(NTFY / "tasks/main.yml")
    directory = _task("Create ntfy auth directory", main)
    assert directory["when"] == "ntfy_docker_ai_jobs_enabled | bool"
    assert directory["ansible.builtin.file"]["mode"] == "0700"
    stage = _task("Provision the ai-jobs publisher credentials", main)
    assert "ntfy_docker_ai_jobs_enabled | bool" in stage["when"]
    assert "not ansible_check_mode" in stage["when"]
    assert stage["block"][0]["ansible.builtin.include_tasks"] == "ai_jobs_publisher.yml"
    assert stage["rescue"], "a failure here must not hold back the other alert-hub stages"


def test_the_topic_is_carried_by_the_hub():
    assert TOPIC in _defaults()["ntfy_docker_topics"]


# --- scope: one user, one topic, write-only -----------------------------------


def _argv(task: dict, variables: dict) -> list[str]:
    return [_render(arg, variables) for arg in task["ansible.builtin.command"]["argv"]]


def test_the_user_is_a_plain_user_never_an_admin():
    argv = _argv(_task("Create the publish-only ntfy user"), _vars())
    assert "--role=user" in argv
    assert argv[-1] == USER
    assert not [arg for arg in argv if "admin" in arg]


def test_the_password_never_reaches_a_command_line():
    task = _task("Create the publish-only ntfy user")
    argv = _argv(task, _vars())
    assert argv[argv.index("--env") + 1] == "NTFY_PASSWORD"
    assert not [arg for arg in argv if arg.startswith("NTFY_PASSWORD=")]
    assert "NTFY_PASSWORD" in task["environment"]
    assert task["no_log"] is True


def test_the_only_grant_is_write_only_on_the_topic():
    argv = _argv(_task("Grant the user write-only access to the topic"), _vars())
    assert argv[argv.index("access") :] == ["access", USER, TOPIC, "write-only"]
    assert "*" not in "".join(argv)
    assert "everyone" not in argv


@pytest.mark.parametrize(
    ("entries", "reset", "grant"),
    [
        ([], False, True),
        (["- write-only access to topic ai-jobs"], False, False),
        (["- read-write access to topic other-topic"], True, True),
        (
            ["- write-only access to topic ai-jobs", "- read-write access to topic other"],
            True,
            True,
        ),
        (["- read-write access to topic ai-jobs"], True, True),
    ],
)
def test_access_converges_to_exactly_one_entry(entries, reset, grant):
    facts = _task("Record the user's topic access entries")["ansible.builtin.set_fact"]
    variables = _vars(
        ntfy_docker_ai_jobs_access={
            "stdout_lines": [f"user {USER} (role: user, tier: none)", *entries]
            if entries
            else [f"user {USER} (role: user, tier: none)", "- no topic-specific permissions"]
        }
    )
    variables["ntfy_docker_ai_jobs_acl_entries"] = _render(
        facts["ntfy_docker_ai_jobs_acl_entries"], variables
    )
    variables["ntfy_docker_ai_jobs_acl_wanted"] = [
        _render(item, variables) for item in facts["ntfy_docker_ai_jobs_acl_wanted"]
    ]
    assert variables["ntfy_docker_ai_jobs_acl_entries"] == entries
    assert _holds(_task("Reset the user's topic access")["when"], variables) is reset
    assert _holds(_task("Grant the user write-only access to the topic")["when"], variables) is grant


# --- token: created once, published as the only field -------------------------


@pytest.mark.parametrize(
    ("listing", "creates"),
    [
        (f"user {USER} has no access tokens", True),
        (f"user {USER}\n- tk_abcdefghijklmnopqrstuvwxyz123 (ai-jobs-dispatcher), never expires", False),
    ],
)
def test_a_token_is_created_only_when_none_exists(listing, creates):
    task = _task("Create the user's access token")
    assert _holds(task["when"], _vars(ntfy_docker_ai_jobs_tokens={"stdout": listing})) is creates
    assert task["no_log"] is True


def test_the_token_is_resolved_from_the_creation_or_the_listing():
    expr = _task("Resolve the access token")["ansible.builtin.set_fact"]["ntfy_docker_ai_jobs_token"]
    created = "token tk_newtokenvalue00000000000000 created for user ai-jobs-publisher, never expires"
    listed = "user ai-jobs-publisher\n- tk_oldtokenvalue00000000000000 (ai-jobs-dispatcher), never expires"
    from_created = _render(
        expr,
        {
            "ntfy_docker_ai_jobs_token_created": {"stdout": created},
            "ntfy_docker_ai_jobs_tokens": {"stdout": "none"},
        },
    )
    from_listing = _render(
        expr,
        {
            "ntfy_docker_ai_jobs_token_created": {"skipped": True},
            "ntfy_docker_ai_jobs_tokens": {"stdout": listed},
        },
    )
    assert from_created == "tk_newtokenvalue00000000000000"
    assert from_listing == "tk_oldtokenvalue00000000000000"


def test_only_the_token_is_published_to_the_open_llm_bucket():
    task = _task("Publish the access token to OpenBao")
    assert task["ansible.builtin.include_role"] == {
        "name": "openbao_secrets",
        "tasks_from": "publish.yml",
    }
    assert task["vars"]["openbao_secrets_publish_app"] == "open-llm"
    assert list(task["vars"]["openbao_secrets_publish_data"]) == ["NTFY_AI_JOBS_TOKEN"]


# --- NTFY_URL rides the open-llm promotion map --------------------------------


def _bucket_defaults() -> dict:
    return _yaml(ROOT / "roles/openbao/defaults/main/01b-app-secrets.yml")


def test_the_ntfy_url_is_promoted_with_the_open_llm_fields(monkeypatch):
    bucket = _bucket_defaults()
    assert bucket["openbao_promoted_app_secrets"]["open-llm"]["NTFY_URL"] == "openbao_open_llm_ntfy_url"
    monkeypatch.setenv("PROXMOX_SUBDOMAIN", "example.test")
    url = _render(bucket["openbao_open_llm_ntfy_url"], {})
    assert url == "https://ntfy.example.test"
    # The publisher and the consumer name the same server.
    assert url == _render(_defaults()["ntfy_docker_base_url"], {"ntfy_docker_container_name": "ntfy"})


# --- the shared publish is a check-and-set merge --------------------------------

PUBLISH = ROOT / "roles/openbao_secrets/tasks/publish.yml"


def _write_task() -> dict:
    def walk(tasks):
        for task in tasks:
            if task.get("name") == "Merge the new fields over the existing secret and write it back":
                return task
            for key in ("block", "rescue", "always"):
                found = walk(task.get(key, []))
                if found:
                    return found
        return None

    task = walk(_yaml(PUBLISH))
    assert task, "write task not found"
    return task["community.hashi_vault.vault_write"]["data"]


def _payload(existing: dict, effective: dict) -> dict:
    data = _write_task()
    variables = {
        "openbao_secrets_publish_existing": existing,
        "openbao_secrets_publish_effective": effective,
    }
    return {
        "cas": _render(data["options"]["cas"], variables),
        "data": _render(data["data"], variables),
    }


def test_the_write_preserves_every_sibling_field():
    existing = {"metadata": {"version": 7}, "secret": {"UNKNOWN_SIBLING": "keep", "NTFY_AI_JOBS_TOKEN": "old"}}
    result = _payload(existing, {"NTFY_AI_JOBS_TOKEN": "new"})
    assert result["data"] == {"UNKNOWN_SIBLING": "keep", "NTFY_AI_JOBS_TOKEN": "new"}


def test_the_write_is_checked_against_the_version_that_was_read():
    existing = {"metadata": {"version": 7}, "secret": {"A": "1"}}
    assert _payload(existing, {"B": "2"})["cas"] == 7


def test_a_path_that_did_not_exist_is_created_with_cas_zero():
    absent = {"msg": "Invalid or missing path ['apps/open-llm'] with secret version 'latest'."}
    result = _payload(absent, {"B": "2"})
    assert result["cas"] == 0
    assert result["data"] == {"B": "2"}


def test_cas_is_an_integer_the_server_accepts():
    assert isinstance(_payload({"metadata": {"version": "3"}, "secret": {}}, {"B": "2"})["cas"], int)
