"""Every Hermes bridge identity logs in to Vikunja with a password resolved from
`bao_apps_secrets[<username>_login_password]` (roles/vikunja
hermes_bridge_password_one.yml, `mandatory`). That field only exists at
secret/apps/vikunja when the openbao role generates it, so each declared
identity must be listed in `openbao_generated_app_secrets.vikunja` -- otherwise
the bridge include aborts for every identity.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PASSWORD_TASK = ROOT / "roles/vikunja/tasks/hermes_bridge_password_one.yml"


def _vikunja_identities() -> list[str]:
    defaults = yaml.safe_load(
        (ROOT / "roles/vikunja/defaults/main.yml").read_text(encoding="utf-8")
    )
    return [item["username"] for item in defaults["vikunja_hermes_bridge_identities"]]


def _generated_vikunja_fields() -> list[str]:
    merged: dict = {}
    for path in sorted((ROOT / "roles/openbao/defaults/main").glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return merged["openbao_generated_app_secrets"]["vikunja"]


def test_the_password_field_name_is_username_login_password():
    # Guards the naming convention the assertion below derives from.
    assert "~ '_login_password'" in PASSWORD_TASK.read_text(encoding="utf-8")


def test_hermes_is_a_declared_bridge_identity():
    # Keeps the contract below from passing vacuously.
    assert "hermes" in _vikunja_identities()


def test_every_bridge_identity_has_a_generated_login_password():
    generated = _generated_vikunja_fields()
    missing = [
        f"{username}_login_password"
        for username in _vikunja_identities()
        if f"{username}_login_password" not in generated
    ]
    assert not missing, f"not generated at secret/apps/vikunja: {missing}"
