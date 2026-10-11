"""Roles of the dryvist.secrets_management collection.

The OpenBao and Authelia roles live in that collection, not in this repository.
Contract tests read their sources from SECRETS_ROLES, the roles directory of the
installed collection. Install it with `ansible-galaxy install -r requirements.yml`
before running pytest.
"""

from pathlib import Path

from ansible import constants as C

COLLECTION_ROLES = Path("ansible_collections", "dryvist", "secrets_management", "roles")


def _installed_roles_dir() -> Path:
    for entry in C.COLLECTIONS_PATHS:
        candidate = Path(entry).expanduser() / COLLECTION_ROLES
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "dryvist.secrets_management is not installed; "
        "run `ansible-galaxy install -r requirements.yml` first"
    )


SECRETS_ROLES = _installed_roles_dir()


def read_secrets_role(rel: str) -> str:
    return (SECRETS_ROLES / rel).read_text(encoding="utf-8")
