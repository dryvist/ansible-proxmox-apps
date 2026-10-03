"""Unit test for roles/homarr/files/homarr_boards.py (Homarr 2.x boards).

`board.saveBoard` deletes every item a call omits, so the converger must send
the whole board with stable ids, skip a widget whose integration failed (2.x
rejects the WHOLE save otherwise), and not re-save an unchanged board.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

# Same loading as test_homarr_board_sync: the sibling homarr_trpc import
# resolves from the files directory, as it does on the guest.
FILES = Path(__file__).resolve().parents[1] / "roles/homarr/files"
if str(FILES) not in sys.path:
    sys.path.insert(0, str(FILES))
SPEC = importlib.util.spec_from_file_location("homarr_boards", FILES / "homarr_boards.py")
assert SPEC and SPEC.loader
homarr_boards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(homarr_boards)


class FakeApi:
    """A minimal 2.x Homarr: one board store that saveBoard replaces."""

    def __init__(self):
        self.boards, self.calls, self.settings = {}, [], {}

    def trpc(self, procedure, payload: dict | None = None, api_key=None, query=False):
        self.calls.append(procedure)
        payload = payload or {}
        if procedure == "board.getBoardByName":
            if payload["name"] not in self.boards:
                raise homarr_boards.HomarrError("NOT_FOUND")
            return self.boards[payload["name"]]
        if procedure == "board.createBoard":
            n = payload["name"]
            self.boards[n] = {
                "id": f"b-{n}", "name": n, "isPublic": payload["isPublic"], "items": [],
                "sections": [{"id": f"s-{n}", "kind": "empty", "xOffset": 0, "yOffset": 0}],
                "layouts": [{"id": f"m-{n}", "role": "mobile", "columnCount": 3},
                            {"id": f"l-{n}", "role": "base", "columnCount": payload["columnCount"]}],
            }
            return {"boardId": f"b-{n}"}
        by_id = {b["id"]: b for b in self.boards.values()}
        if procedure == "board.saveBoard":
            by_id[payload["id"]]["items"] = payload["items"]
        elif procedure == "board.changeBoardVisibility":
            by_id[payload["id"]]["isPublic"] = payload["visibility"] == "public"
        elif procedure == "serverSettings.getBoardSettings":
            return dict(self.settings)
        elif procedure == "serverSettings.updateBoardSettings":
            self.settings.update(payload)
        return None


WIDGETS = {
    "clock": {"kind": "clock", "size": {"base": [3, 1], "mobile": [3, 1]}},
    "plex": {"kind": "mediaServer", "integrations": ["plex"], "size": {"base": [6, 2], "mobile": [3, 2]}},
    "calendar": {"kind": "calendar", "integrations": ["sonarr"], "size": {"base": [4, 3], "mobile": [3, 3]}},
    "health": {"kind": "stats", "integrations": ["gatus"], "stats_metrics": {"gatus": ["up", "down"]},
               "size": {"base": [3, 1], "mobile": [3, 1]}},
}
BOARDS = [{"name": "everything", "columns": 12, "public": True, "home": True, "apps": True,
           "widgets": ["clock", "plex", "calendar", "health"]}]
INTEGRATIONS = [{"id": "i-gatus", "kind": "gatus"}]  # plex and sonarr failed to save
CATALOG = [{"name": "grafana", "group": "ops", "ui": True}, {"name": "api", "group": "ops", "ui": False}]


class Boards(unittest.TestCase):
    def converge(self, api):
        return homarr_boards.sync_boards(api, "k", BOARDS, WIDGETS, INTEGRATIONS, CATALOG, {"grafana": "a1"})

    def test_pack_wraps_at_the_column_count(self):
        self.assertEqual(homarr_boards.pack([(3, 1), (6, 2), (4, 3)], 12), [(0, 0), (3, 0), (0, 2)])
        self.assertEqual(homarr_boards.pack([(6, 1)], 3), [(0, 0)])

    def test_first_converge_builds_the_whole_board(self):
        api = FakeApi()
        actions, changed = self.converge(api)
        self.assertTrue(changed)
        board = api.boards["everything"]
        ids = [item["id"] for item in board["items"]]
        # plex lost its integration and is skipped; calendar renders without one.
        self.assertEqual(ids, ["everything-clock", "everything-calendar", "everything-health",
                               "everything-apps-ops"])
        self.assertIn("board everything: skipped plex (no working integration)", actions)
        health = board["items"][2]
        self.assertEqual(health["integrationIds"], ["i-gatus"])
        self.assertEqual([e["metric"] for e in health["options"]["entries"]], ["up", "down"])
        # Only UI catalog rows become bookmarks.
        self.assertEqual(board["items"][3]["options"]["items"], ["a1"])
        # Both layouts are placed; the mobile one never exceeds its 3 columns.
        for item in board["items"]:
            self.assertEqual({lay["layoutId"] for lay in item["layouts"]}, {"m-everything", "l-everything"})
            mobile = next(lay for lay in item["layouts"] if lay["layoutId"] == "m-everything")
            self.assertLessEqual(mobile["xOffset"] + mobile["width"], 3)
        self.assertEqual(api.settings, {"homeBoardId": "b-everything", "mobileHomeBoardId": "b-everything"})

    def test_second_converge_changes_nothing(self):
        api = FakeApi()
        self.converge(api)
        api.calls.clear()
        _, changed = self.converge(api)
        self.assertFalse(changed)
        self.assertNotIn("board.saveBoard", api.calls)


if __name__ == "__main__":
    unittest.main()
