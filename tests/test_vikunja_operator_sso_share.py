"""The operator's SSO account receives the same project shares as the local one.

A first OIDC login provisions a NEW Vikunja account keyed on issuer+subject,
with a site-specific username Vikunja generates itself — it is never committed
to this public repo. The role resolves it at converge time from the
`vikunja user list` table (rows whose EMAIL cell is the operator's email and
whose ISSUER cell is not `local`) into the vikunja_operator_sso_usernames
fact, then loops the share reconciler over every grantee in
vikunja_operator_share_users: the local operator username plus that SSO
username.

These render the REAL expressions out of the defaults and task files. The
sample tables are in the format the pinned Vikunja CLI prints (tablewriter's
default StyleLight: │ cell separators, cells ID, USERNAME, EMAIL, STATUS,
ISSUER, SUBJECT, CREATED, UPDATED).
"""

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from vikunja_hermes_task_support import ROOT, defaults, find, render, render_template

ROLE = ROOT / "roles/vikunja"
MAIN = "roles/vikunja/tasks/main.yml"
OPERATOR_ACCESS = "roles/vikunja/tasks/operator_access.yml"

SSO_FACT_NAME = "Resolve the operator's SSO usernames from the user list"
GRANT_INCLUDE_NAME = "Grant the operator access to the automation-owned projects"
GRANT_LOOP_NAME = "Share automation-owned projects with the operator, per owning account"

OPERATOR_USERNAME = "jevans"
OPERATOR_EMAIL = f"{OPERATOR_USERNAME}@home.example.tld"
SSO_USERNAME = "openid-7f3a"
PARTNER_EMAIL = "partner@home.example.tld"

# A first login for the operator, an unrelated SSO account, and a local-only
# table — the parse must never return the partner or any local account.
SAMPLE_TABLE = "\n".join(
    [
        "┌────┬──────────────┬──────────────────────────────┬────────┬──────────┬──────────────────┬──────────────────────┬──────────────────────┐",
        "│ ID │ USERNAME     │ EMAIL                        │ STATUS │ ISSUER   │ SUBJECT          │ CREATED              │ UPDATED              │",
        "├────┼──────────────┼──────────────────────────────┼────────┼──────────┼──────────────────┼──────────────────────┼──────────────────────┤",
        "│ 1  │ admin        │ admin@home.example.tld       │ active │ local    │                  │ 2026-01-02T03:04:05Z │ 2026-01-02T03:04:05Z │",
        "│ 2  │ svc-mcp-rw   │ svc-mcp-rw@home.example.tld  │ active │ local    │                  │ 2026-01-02T03:04:05Z │ 2026-01-02T03:04:05Z │",
        "│ 3  │ jevans       │ jevans@home.example.tld      │ active │ local    │                  │ 2026-01-02T03:04:05Z │ 2026-01-02T03:04:05Z │",
        "│ 4  │ openid-7f3a  │ jevans@home.example.tld      │ active │ authelia │ authelia-jevans  │ 2026-02-03T04:05:06Z │ 2026-02-03T04:05:06Z │",
        "│ 5  │ oidc-partner │ partner@home.example.tld     │ active │ authelia │ authelia-partner │ 2026-03-04T05:06:07Z │ 2026-03-04T05:06:07Z │",
        "│ 6  │ substring    │ jevans@home.example.tld.evil │ active │ authelia │ authelia-decoy   │ 2026-03-04T05:06:07Z │ 2026-03-04T05:06:07Z │",
        "└────┴──────────────┴──────────────────────────────┴────────┴──────────┴──────────────────┴──────────────────────┴──────────────────────┘",
    ]
)

LOCAL_ONLY_TABLE = "\n".join(
    [
        "┌────┬──────────────┬─────────────────────────────┬────────┬────────┬─────────┬──────────────────────┬──────────────────────┐",
        "│ ID │ USERNAME     │ EMAIL                       │ STATUS │ ISSUER │ SUBJECT │ CREATED              │ UPDATED              │",
        "├────┼──────────────┼─────────────────────────────┼────────┼────────┼─────────┼──────────────────────┼──────────────────────┤",
        "│ 1  │ admin        │ admin@home.example.tld      │ active │ local  │         │ 2026-01-02T03:04:05Z │ 2026-01-02T03:04:05Z │",
        "│ 3  │ jevans       │ jevans@home.example.tld     │ active │ local  │         │ 2026-01-02T03:04:05Z │ 2026-01-02T03:04:05Z │",
        "└────┴──────────────┴─────────────────────────────┴────────┴────────┴─────────┴──────────────────────┴──────────────────────┘",
    ]
)


def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, list):
        return [_trusted(item) for item in value]
    if isinstance(value, dict):
        return {key: _trusted(item) for key, item in value.items()}
    return value


def _render(value, variables):
    """Render a value that may be a nested structure of templated strings."""
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(_trusted(value))


def sso_fact():
    return find(SSO_FACT_NAME, MAIN)


def grant_include():
    return find(GRANT_INCLUDE_NAME, MAIN)


def grant_loop():
    return find(GRANT_LOOP_NAME, OPERATOR_ACCESS)


def resolve_sso(stdout, operator_email=OPERATOR_EMAIL):
    """Run the real set_fact expression over a given user-list stdout."""
    registered = {"changed": False}
    if stdout is not None:
        registered["stdout"] = stdout
    return render_template(
        sso_fact()["ansible.builtin.set_fact"]["vikunja_operator_sso_usernames"],
        {
            "vikunja_user_list": registered,
            "vikunja_operator_email": operator_email,
        },
    )


def share_users(variables):
    """Render the real vikunja_operator_share_users default."""
    return _render(defaults()["vikunja_operator_share_users"], variables)


# --- the SSO username is resolved at converge time, never committed -------------


def test_the_sso_username_fact_is_not_declared_in_defaults():
    assert "vikunja_operator_sso_usernames" not in defaults()


def test_the_share_default_references_the_fact_not_a_username():
    expression = str(defaults()["vikunja_operator_share_users"])
    assert "vikunja_operator_sso_usernames" in expression
    assert "openid" not in expression and "jevans" not in expression


def test_the_sso_fact_is_resolved_before_the_shares_are_granted():
    names = [task.get("name") for task in _yaml(ROOT / MAIN)]
    assert names.index(SSO_FACT_NAME) < names.index(GRANT_INCLUDE_NAME)


def test_the_sso_fact_logs_nothing_like_its_neighbours():
    assert sso_fact().get("no_log") is True
    assert grant_include().get("no_log") is True


# --- the parse: non-local rows with the operator's email ------------------------


def test_the_parse_returns_exactly_the_operator_s_sso_rows():
    assert resolve_sso(SAMPLE_TABLE) == [SSO_USERNAME]


def test_the_parse_ignores_local_accounts_and_other_sso_emails():
    resolved = resolve_sso(SAMPLE_TABLE)
    assert OPERATOR_USERNAME not in resolved
    assert "oidc-partner" not in resolved


def test_a_similar_but_distinct_email_resolves_only_its_own_row():
    # Row 6's EMAIL contains the operator's email as a substring, so the
    # operator's parse (above) never returns it — but that cell is an exact
    # match for its own address, and its issuer is not local.
    assert resolve_sso(SAMPLE_TABLE, "jevans@home.example.tld.evil") == ["substring"]


def test_a_table_without_sso_logins_resolves_empty():
    assert resolve_sso(LOCAL_ONLY_TABLE) == []


def test_an_empty_user_list_resolves_empty():
    assert resolve_sso("") == []


def test_an_absent_user_list_stdout_resolves_empty():
    # --check skips the command task, leaving no stdout — same contract as the
    # idempotent create tasks in tasks/main.yml.
    assert resolve_sso(None) == []


# --- the share list: local operator + SSO account -------------------------------


def test_the_share_list_contains_the_local_operator_and_the_sso_username():
    users = share_users(
        {
            "vikunja_operator_username": OPERATOR_USERNAME,
            "vikunja_operator_sso_usernames": [SSO_USERNAME],
        }
    )
    assert users == [OPERATOR_USERNAME, SSO_USERNAME]


def test_the_share_list_still_works_before_any_sso_login():
    users = share_users(
        {
            "vikunja_operator_username": OPERATOR_USERNAME,
            "vikunja_operator_sso_usernames": [],
        }
    )
    assert users == [OPERATOR_USERNAME]


def test_the_share_list_survives_an_undefined_sso_fact():
    # Templating must not fail where the fact was never set (fresh host run).
    users = share_users({"vikunja_operator_username": OPERATOR_USERNAME})
    assert users == [OPERATOR_USERNAME]


# --- every grantee gets every owned project -------------------------------------


def _grantee_owner_pairs():
    users = share_users(
        {
            "vikunja_operator_username": OPERATOR_USERNAME,
            "vikunja_operator_sso_usernames": [SSO_USERNAME],
        }
    )
    return render_template(
        grant_loop()["loop"],
        {
            "vikunja_operator_share_users": users,
            "vikunja_operator_share_owner_usernames": ["admin", "svc-mcp-rw"],
        },
    )


def test_the_loop_pairs_every_grantee_with_every_owner():
    assert _grantee_owner_pairs() == [
        [OPERATOR_USERNAME, "admin"],
        [OPERATOR_USERNAME, "svc-mcp-rw"],
        [SSO_USERNAME, "admin"],
        [SSO_USERNAME, "svc-mcp-rw"],
    ]


def test_the_loop_reuses_the_shared_reconciler():
    assert grant_loop()["ansible.builtin.include_tasks"] == "operator_access_one.yml"


def test_each_pair_drives_the_reconciler_with_the_pair_grantee_and_owner():
    loop_vars = grant_loop()["vars"]
    pair = (SSO_USERNAME, "svc-mcp-rw")
    rendered = {key: render_template(value, {"vikunja_share_pair": pair, "vikunja_operator_permission": 2}) for key, value in loop_vars.items()}
    assert rendered["vikunja_share_grantee_username"] == SSO_USERNAME
    assert rendered["vikunja_share_owner"] == "svc-mcp-rw"
    assert rendered["vikunja_share_permission"] == 2


def test_an_empty_grantee_is_skipped():
    when = grant_loop()["when"]
    variables = {
        "vikunja_share_pair": ("", "svc-mcp-rw"),
        "vikunja_project_share_owner_password_map": {"svc-mcp-rw": "pw"},
    }
    assert render(when, variables) is False


def test_an_owner_without_a_resolvable_credential_is_skipped():
    when = grant_loop()["when"]
    variables = {
        "vikunja_share_pair": (SSO_USERNAME, "admin"),
        "vikunja_project_share_owner_password_map": {"svc-mcp-rw": "pw"},
    }
    assert render(when, variables) is False


def test_a_provisioned_pair_is_shared():
    when = grant_loop()["when"]
    variables = {
        "vikunja_share_pair": (SSO_USERNAME, "svc-mcp-rw"),
        "vikunja_project_share_owner_password_map": {"svc-mcp-rw": "pw"},
    }
    assert render(when, variables) is True


# --- additive only: no revoke in the operator share path ------------------------


def test_the_operator_share_path_never_revokes():
    for rel in (
        MAIN,
        OPERATOR_ACCESS,
        "roles/vikunja/tasks/operator_access_one.yml",
        "roles/vikunja/tasks/operator_access_project.yml",
    ):
        for task in _yaml(ROOT / rel) or []:
            assert (task.get("ansible.builtin.uri") or {}).get("method") != "DELETE", rel


def test_the_agent_tier_contract_on_the_shared_reconciler_is_untouched():
    # agent_tier_reconcile.yml includes the same reconciler with the same
    # loop_var contract — the operator changes must not have altered it.
    tasks = _yaml(ROOT / "roles/vikunja/tasks/agent_tier_reconcile.yml")
    regrant = next(task for task in tasks if task.get("ansible.builtin.include_tasks") == "operator_access_one.yml")
    assert regrant["loop_control"]["loop_var"] == "vikunja_share_owner"
    assert regrant["vars"]["vikunja_share_grantee_username"] == "{{ vikunja_agent_tier.username }}"
    deletes = [
        task
        for file in ("roles/vikunja/tasks/agent_tier_reconcile.yml", "roles/vikunja/tasks/agent_revoke_direct_share.yml")
        for task in _yaml(ROOT / file) or []
        if (task.get("ansible.builtin.uri") or {}).get("method") == "DELETE"
    ]
    assert len(deletes) >= 2
