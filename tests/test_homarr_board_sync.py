"""Unit test for the board-tile diff in roles/homarr/files/homarr_api.py.

Homarr's `app.create` and `board.addItem` tRPC procedures always insert — there
is no upsert. This pins the diff-by-name/diff-by-id logic that makes repeated
converges idempotent instead of doubling every tile.
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


class FakeApi:
    """Records every tRPC call and answers from a small in-memory Homarr."""

    def __init__(self, apps=None, board=None):
        self.apps = {a["name"]: dict(a) for a in (apps or [])}
        self.board = board
        self.calls = []
        self._next_id = 1

    def _new_id(self):
        self._next_id += 1
        return f"id{self._next_id}"

    def trpc(self, procedure, payload=None, api_key=None, query=False):
        self.calls.append((procedure, payload))
        if procedure in ("app.create", "app.update"):
            # Mirrors Homarr's real appManageSchema. Every field there is
            # `.nullable()` but NOT `.optional()`, so an OMITTED key is a
            # validation error even when the value would legitimately be null
            # — the exact defect a laxer fake let through to CI twice. null is
            # fine; absent is not.
            for field in ("name", "description", "iconUrl", "href", "pingUrl"):
                if field not in payload:
                    raise homarr_api.HomarrError(
                        f"{procedure} -> HTTP 400: {field} received undefined"
                    )
            if not payload.get("iconUrl"):
                raise homarr_api.HomarrError(
                    f"{procedure} -> HTTP 400: iconUrl too_small"
                )
        if procedure == "app.all":
            return list(self.apps.values())
        if procedure == "app.create":
            row = {"id": self._new_id(), "href": payload["href"], **payload}
            self.apps[payload["name"]] = row
            return row
        if procedure == "app.update":
            self.apps[payload["name"]].update(payload)
            return None
        if procedure in ("board.getBoardByName", "board.getHomeBoard"):
            # getBoardByName is a tRPC *query* with input, so sync_board must
            # ask for it as a GET; a POST is rejected. Assert the flag here,
            # since the wrong method looked exactly like a missing board.
            if procedure == "board.getBoardByName" and not query:
                raise AssertionError("getBoardByName is a query — must pass query=True")
            if self.board is None:
                raise homarr_api.HomarrError("NOT_FOUND")
            return self.board
        if procedure == "board.addItem":
            self.board["items"].append(
                {"kind": payload["kind"], "options": payload["options"]}
            )
            return {"itemId": self._new_id()}
        raise AssertionError(f"unexpected procedure: {procedure}")


def test_new_app_is_created_and_placed():
    api = FakeApi(board={"id": "b1", "items": []})
    apps = [{"name": "Sonarr", "url": "https://sonarr.example.test", "desc": "TV"}]

    actions, changed = homarr_api.sync_board(api, "key", "default", apps)

    assert changed is True
    assert any(c[0] == "app.create" for c in api.calls)
    assert any(c[0] == "board.addItem" for c in api.calls)
    assert "Sonarr" in api.apps
    assert len(api.board["items"]) == 1


def test_unchanged_app_already_on_board_is_a_pure_noop():
    existing = {"id": "app1", "name": "Sonarr", "href": "https://sonarr.example.test"}
    board = {"id": "b1", "items": [{"kind": "app", "options": {"appId": "app1"}}]}
    api = FakeApi(apps=[existing], board=board)
    apps = [{"name": "Sonarr", "url": "https://sonarr.example.test", "desc": "TV"}]

    actions, changed = homarr_api.sync_board(api, "key", "default", apps)

    assert changed is False
    assert actions == []
    assert not any(c[0] in ("app.create", "app.update", "board.addItem") for c in api.calls)


def test_drifted_href_updates_without_re_adding_the_tile():
    existing = {"id": "app1", "name": "Sonarr", "href": "https://old.example.test"}
    board = {"id": "b1", "items": [{"kind": "app", "options": {"appId": "app1"}}]}
    api = FakeApi(apps=[existing], board=board)
    apps = [{"name": "Sonarr", "url": "https://sonarr.example.test", "desc": "TV"}]

    actions, changed = homarr_api.sync_board(api, "key", "default", apps)

    assert changed is True
    assert any(c[0] == "app.update" for c in api.calls)
    assert not any(c[0] == "board.addItem" for c in api.calls)
    assert len(board["items"]) == 1  # the exact regression this guards against


def test_missing_board_is_reported_not_a_crash():
    # The app itself is still created (independent of board placement), so
    # `changed` is True from that step — only the tile placement is skipped.
    api = FakeApi(board=None)
    apps = [{"name": "Sonarr", "url": "https://sonarr.example.test"}]

    actions, changed = homarr_api.sync_board(api, "key", "default", apps)

    assert changed is True
    assert not any(c[0] == "board.addItem" for c in api.calls)
    assert any("does not exist" in a for a in actions)
