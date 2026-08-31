"""Unit test for the integration diff in roles/homarr/files/homarr_api.py.

Homarr's `integrationUpdateSchema` makes `appId` `.nullable()` but NOT
`.optional()`, and `update` writes it straight into the row's `set` clause.
Two distinct failures follow from that, and only the first is loud:

  * Omitting the key is a zod 400 ("expected string, received undefined").
    It stayed latent for as long as no integration URL ever drifted -- the
    update path simply never ran -- and surfaced the first time one did.
  * Sending null when an app IS linked silently unlinks it. `integration.all`
    does not return appId; only `integration.byId` does. So the value has to
    be read back per integration, not defaulted.

The fake below enforces the real schema in both directions.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# homarr_api imports its sibling homarr_trpc the same way it does on the guest:
# from its own directory, via sys.path[0]. Loading it by file path bypasses that,
# so put the directory on sys.path explicitly.
FILES = ROOT / "roles/homarr/files"
if str(FILES) not in sys.path:
    sys.path.insert(0, str(FILES))
SPEC = importlib.util.spec_from_file_location("homarr_api", FILES / "homarr_api.py")
homarr_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(homarr_api)

SECRET = [{"kind": "apiKey", "value": "k"}]


class FakeApi:
    """A small in-memory Homarr that enforces integrationUpdateSchema."""

    def __init__(self, rows=None):
        # rows: {name: {"id","kind","url","app": {"id"} | None}}
        self.rows = {r["name"]: dict(r) for r in (rows or [])}
        self.calls = []

    def trpc(self, procedure, payload=None, api_key=None, query=False):
        self.calls.append((procedure, payload))
        if procedure == "integration.all":
            # Mirrors the real projection: id/name/kind/url only. No appId.
            return [
                {k: r[k] for k in ("id", "name", "kind", "url")}
                for r in self.rows.values()
            ]
        if procedure == "integration.byId":
            if not query:
                raise AssertionError("integration.byId is a query — needs query=True")
            row = next(r for r in self.rows.values() if r["id"] == payload["id"])
            return {**row, "app": row.get("app")}
        if procedure == "integration.create":
            self.rows[payload["name"]] = {
                "id": "new1",
                "name": payload["name"],
                "kind": payload["kind"],
                "url": payload["url"],
                "app": None,
            }
            return None
        if procedure == "integration.update":
            if "appId" not in payload:
                raise homarr_api.HomarrError(
                    "integration.update -> HTTP 400: appId received undefined"
                )
            row = next(r for r in self.rows.values() if r["id"] == payload["id"])
            row["url"] = payload["url"]
            # update assigns appId unconditionally, so null really does unlink.
            row["app"] = {"id": payload["appId"]} if payload["appId"] else None
            return None
        raise AssertionError(f"unexpected procedure: {procedure}")


def test_drifted_url_updates_and_sends_appid():
    api = FakeApi([{"id": "i1", "name": "Sonarr", "kind": "sonarr",
                    "url": "http://old.example.test:8989", "app": None}])
    want = [{"name": "Sonarr", "kind": "sonarr",
             "url": "https://sonarr.example.test", "secrets": SECRET}]

    actions, changed = homarr_api.sync_integrations(api, "key", want)

    assert changed is True
    update = next(p for proc, p in api.calls if proc == "integration.update")
    assert "appId" in update  # the zod 400 this guards against
    assert api.rows["Sonarr"]["url"] == "https://sonarr.example.test"


def test_update_preserves_a_linked_app():
    api = FakeApi([{"id": "i1", "name": "Sonarr", "kind": "sonarr",
                    "url": "http://old.example.test:8989", "app": {"id": "app7"}}])
    want = [{"name": "Sonarr", "kind": "sonarr",
             "url": "https://sonarr.example.test", "secrets": SECRET}]

    homarr_api.sync_integrations(api, "key", want)

    # Defaulting appId to None instead of reading it back would wipe this.
    assert api.rows["Sonarr"]["app"] == {"id": "app7"}


def test_unchanged_integration_is_a_pure_noop():
    api = FakeApi([{"id": "i1", "name": "Sonarr", "kind": "sonarr",
                    "url": "https://sonarr.example.test", "app": None}])
    want = [{"name": "Sonarr", "kind": "sonarr",
             "url": "https://sonarr.example.test", "secrets": SECRET}]

    actions, changed = homarr_api.sync_integrations(api, "key", want)

    assert changed is False
    assert actions == []
    assert not any(
        p in ("integration.update", "integration.byId", "integration.create")
        for p, _ in api.calls
    )


def test_missing_integration_is_created_without_appid():
    api = FakeApi()
    want = [{"name": "Sonarr", "kind": "sonarr",
             "url": "https://sonarr.example.test", "secrets": SECRET}]

    actions, changed = homarr_api.sync_integrations(api, "key", want)

    assert changed is True
    create = next(p for proc, p in api.calls if proc == "integration.create")
    # create's `app` is .optional() — unlike update's appId, absent is legal.
    assert "appId" not in create


def test_integration_without_a_credential_is_skipped_loudly():
    api = FakeApi()
    want = [{"name": "Sonarr", "kind": "sonarr", "url": "https://sonarr.example.test",
             "secrets": [{"kind": "apiKey", "value": ""}]}]

    actions, changed = homarr_api.sync_integrations(api, "key", want)

    assert changed is False
    assert any("Sonarr" in a and "skipped" in a for a in actions)
