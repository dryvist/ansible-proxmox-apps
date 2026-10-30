"""Roles and catalogs of the dryvist collections that the contract tests read.

The OpenBao and Authelia roles live in dryvist.secrets_management, and the
resource-domain reader role lives in dryvist.homelab. Contract tests read their
sources from the installed collections. Run
`python3 scripts/install_galaxy_requirements.py` before running pytest.
"""

from pathlib import Path

from ansible import constants as C

COLLECTION_ROOT = Path("ansible_collections", "dryvist")


def _installed_collection(name: str) -> Path:
    for entry in C.COLLECTIONS_PATHS:
        candidate = Path(entry).expanduser() / COLLECTION_ROOT / name
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        f"dryvist.{name} is not installed; "
        "run `python3 scripts/install_galaxy_requirements.py` first"
    )


SECRETS_COLLECTION = _installed_collection("secrets_management")
SECRETS_ROLES = SECRETS_COLLECTION / "roles"
# The OpenBao resource-domain catalog: each domain and its KV paths.
SECRETS_DOMAIN_CATALOG = (
    SECRETS_COLLECTION / "playbooks" / "group_vars" / "all" / "openbao_secrets.yml"
)
HOMELAB_ROLES = _installed_collection("homelab") / "roles"


def read_secrets_role(rel: str) -> str:
    return (SECRETS_ROLES / rel).read_text(encoding="utf-8")
