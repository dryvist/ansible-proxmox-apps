"""Traefik dashboard secret checks preserve the check-mode and resync contract."""

import base64
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
TASKS = yaml.safe_load((ROOT / "roles/traefik/tasks/dashboard_auth.yml").read_text())
DEFAULTS = yaml.safe_load((ROOT / "roles/traefik/defaults/main.yml").read_text())

_JINJA = Environment(keep_trailing_newline=True)
_JINJA.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
_JINJA.filters["bool"] = lambda value: str(value).lower() in {"1", "true", "yes", "on"}


def _task(name):
    return next(task for task in TASKS if task.get("name") == name)


def _evaluate(expression, variables):
    return _JINJA.compile_expression(expression)(**variables)


def _holds(conditions, variables):
    if not isinstance(conditions, list):
        conditions = [conditions]
    return all(_evaluate(condition, variables) for condition in conditions)


def _assertions_hold(task, variables):
    return all(
        _evaluate(assertion, variables)
        for assertion in task["ansible.builtin.assert"]["that"]
    )


def _case(resync, drift):
    expected = "stored"
    persisted = "different" if drift == "password" else expected
    encoded = base64.b64encode(f"user:{persisted}".encode()).decode()
    return {
        "traefik_dashboard_password_resync_from_openbao": resync,
        "traefik_dashboard_password_seed": {"dashboard_password": expected},
        "traefik_dashboard_password": expected,
        "traefik_dashboard_user": "user",
        "existing_plaintext": f"user:{persisted}\n",
        "traefik_dashboard_password_file": "/test/password",
        "traefik_dashboard_users_file": "/test/htpasswd",
        "traefik_dashboard_password_stat": {"stat": {"exists": True}},
        "traefik_dashboard_password_blob": {"content": encoded},
        "traefik_htpasswd_stat": {"stat": {"exists": True}},
        "traefik_htpasswd_check": {"rc": 1 if drift == "htpasswd" else 0},
        "traefik_user": "traefik",
        "traefik_group": "traefik",
    }


def test_traefik_dashboard_credential_publish_is_skipped_in_check_mode():
    publish = _task("Publish Traefik dashboard metadata to OpenBao")

    assert "not ansible_check_mode" in publish["when"]


@pytest.mark.parametrize("resync", [False, True], ids=["disabled", "enabled"])
@pytest.mark.parametrize("drift", [None, "password", "htpasswd"], ids=["clean", "password", "htpasswd"])
def test_dashboard_password_drift_resync_contract(resync, drift):
    variables = _case(resync, drift)
    needed_task = _task("Check whether either dashboard password copy differs from OpenBao")
    expression = needed_task["ansible.builtin.set_fact"][
        "traefik_dashboard_password_resync_needed"
    ].strip()[2:-2].strip()
    variables["traefik_dashboard_password_resync_needed"] = _evaluate(expression, variables)

    password_assert = _task("Require the persisted dashboard password to match OpenBao")
    htpasswd_assert = _task("Require the existing htpasswd value to match OpenBao")
    password_backup = _task("Back up the existing dashboard password file before resync")
    htpasswd_backup = _task("Back up the existing dashboard htpasswd file before resync")
    render_password = _task("Persist the plaintext dashboard password (root-only)")
    render_htpasswd = _task("Compute the bcrypt htpasswd line")
    install_htpasswd = _task("Install the htpasswd file (basicAuth usersFile)")

    assert DEFAULTS["traefik_dashboard_password_resync_from_openbao"] is False
    assert _holds(password_assert["when"], variables) is (drift != "password" or not resync)
    assert _holds(htpasswd_assert["when"], variables) is (drift != "htpasswd" or not resync)
    if resync or not drift:
        for assertion in (password_assert, htpasswd_assert):
            if _holds(assertion["when"], variables):
                assert _assertions_hold(assertion, variables)

    if drift and not resync:
        mismatched_assert = password_assert if drift == "password" else htpasswd_assert
        assert not _assertions_hold(mismatched_assert, variables)
        assert not _holds(password_backup["when"], variables)
        assert not _holds(htpasswd_backup["when"], variables)
        assert not _holds(render_htpasswd["when"], variables)
        assert not _holds(install_htpasswd["when"], variables)
        return

    if drift and resync:
        assert _holds(password_backup["when"], variables)
        assert _holds(htpasswd_backup["when"], variables)
        assert _holds(render_password["when"], variables)
        assert _holds(render_htpasswd["when"], variables)
        assert _holds(install_htpasswd["when"], variables)
        for backup in (password_backup, htpasswd_backup):
            options = backup["ansible.builtin.copy"]
            assert options["remote_src"] is True
            expected_src_expression = (
                "{{ traefik_dashboard_password_file }}"
                if backup is password_backup
                else "{{ traefik_dashboard_users_file }}"
            )
            assert options["src"] == expected_src_expression
            assert options["owner"] == "root"
            assert options["group"] == "root"
            assert options["mode"] == "0600"
            assert backup["no_log"] is True
            assert options["dest"] == (
                f"{expected_src_expression}.{{{{ now(utc=true, fmt='%Y%m%dT%H%M%SZ') }}}}.bak"
            )
        return

    assert _assertions_hold(password_assert, variables)
    assert _assertions_hold(htpasswd_assert, variables)
    assert _holds(render_password["when"], variables)
    rendered_password = _JINJA.from_string(
        render_password["ansible.builtin.copy"]["content"]
    ).render(**variables)
    assert rendered_password == variables["existing_plaintext"]
    assert not _holds(password_backup["when"], variables)
    assert not _holds(htpasswd_backup["when"], variables)
    assert not _holds(render_htpasswd["when"], variables)
    assert not _holds(install_htpasswd["when"], variables)


def test_dashboard_secret_placeholder_skips_resync_tasks_in_check_mode():
    variables = _case(True, "password")
    variables["traefik_dashboard_password_seed"]["dashboard_password"] = (
        "(placeholder in check mode)"
    )

    guarded = (
        "Require the persisted dashboard password to match OpenBao",
        "Check that the existing htpasswd file matches OpenBao",
        "Require the existing htpasswd value to match OpenBao",
        "Check whether either dashboard password copy differs from OpenBao",
        "Back up the existing dashboard password file before resync",
        "Back up the existing dashboard htpasswd file before resync",
        "Persist the plaintext dashboard password (root-only)",
        "Compute the bcrypt htpasswd line",
        "Install the htpasswd file (basicAuth usersFile)",
    )
    for name in guarded:
        assert not _holds(_task(name)["when"], variables)
