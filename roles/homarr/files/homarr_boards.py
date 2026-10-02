#!/usr/bin/env python3
"""Declarative Homarr 2.x boards: the board in the spec IS the board.

Managed by Ansible (roles/homarr) -- do not edit on the guest. Imported by the
`homarr-api` entrypoint beside it, like homarr_trpc.

`board.saveBoard` replaces a board's items wholesale: anything the call omits
is deleted. So every managed item gets a stable id derived from its board and
widget, and a converge sends the full desired item list. Re-sending an
unchanged board is skipped by comparing it with what Homarr returns, which is
what keeps a second converge from reporting a change.

Positions are not hand-written. Each widget declares a size per layout, and
`pack` flows the board's widgets left to right into the layout's column count,
in declaration order. A 2.x board always has a `mobile` and a `base` layout;
both are packed, so one spec yields the phone and the desktop view.

Stdlib only -- the guest carries no pip packages and must not need any.
"""

import json
import math

from homarr_trpc import HomarrError

ADVANCED_DEFAULTS = {"title": None, "customCssClasses": [], "borderColor": ""}

# Widgets Homarr renders without an integration even though they accept one.
OPTIONAL_INTEGRATION_KINDS = {"calendar"}


def pack(sizes, columns):
    """Shelf-pack (width, height) boxes into `columns`. Returns (x, y) per box."""
    positions, x, y, shelf = [], 0, 0, 0
    for width, height in sizes:
        width = min(width, columns)
        if x + width > columns:
            x, y, shelf = 0, y + shelf, 0
        positions.append((x, y))
        x, shelf = x + width, max(shelf, height)
    return positions


def app_widgets(catalog, app_ids):
    """One bookmarks widget per catalog group of UI routes, in catalog order."""
    groups = {}
    for row in catalog:
        if row.get("ui") and row["name"] in app_ids:
            groups.setdefault(row.get("group") or "other", []).append(app_ids[row["name"]])
    widgets = {}
    for group, ids in groups.items():
        height = max(1, math.ceil(len(ids) / 4))
        widgets[f"apps-{group}"] = {
            "kind": "bookmarks",
            "options": {"title": group, "layout": "grid", "items": ids},
            "size": {"base": [4, height], "mobile": [3, height]},
        }
    return widgets


def stats_entries(widget, integrations):
    """Build a stats widget's entries from {integration kind: [metrics]}."""
    entries = []
    for row in integrations:
        for metric in widget.get("stats_metrics", {}).get(row["kind"], []):
            entries.append({
                "id": f"{row['kind']}-{metric}",
                "integrationId": row["id"],
                "metric": metric,
                "label": metric.title(),
                "hidden": False,
                "compact": False,
            })
    return entries


def desired_items(board, spec_board, widgets, by_kind):
    """The full item list for one board, plus any widgets that had to be skipped."""
    layouts = {layout["role"]: layout for layout in board["layouts"]}
    section = next(
        s["id"] for s in board["sections"] if s["kind"] == "empty" and s["xOffset"] == 0
    )
    chosen, skipped = [], []
    for key in spec_board["widgets"]:
        widget = widgets[key]
        integrations = [row for kind in widget.get("integrations", []) for row in by_kind.get(kind, [])]
        if widget.get("integrations") and not integrations and widget["kind"] not in OPTIONAL_INTEGRATION_KINDS:
            skipped.append(key)
            continue
        chosen.append((key, widget, integrations))

    items = [
        {
            "id": f"{spec_board['name']}-{key}",
            "kind": widget["kind"],
            "options": dict(widget.get("options", {}),
                            **({"entries": stats_entries(widget, rows)} if widget["kind"] == "stats" else {})),
            "advancedOptions": dict(ADVANCED_DEFAULTS, title=widget.get("title")),
            "integrationIds": sorted(row["id"] for row in rows),
            "layouts": [],
        }
        for key, widget, rows in chosen
    ]
    for role in ("mobile", "base"):
        layout = layouts[role]
        sizes = [tuple(widget["size"][role]) for _, widget, _ in chosen]
        for item, (width, height), (x, y) in zip(items, sizes, pack(sizes, layout["columnCount"])):
            item["layouts"].append({
                "layoutId": layout["id"], "sectionId": section,
                "xOffset": x, "yOffset": y,
                "width": min(width, layout["columnCount"]), "height": height,
            })
    return items, skipped


def _canonical(items):
    keep = ("id", "kind", "options", "advancedOptions", "integrationIds", "layouts")
    rows = []
    for item in items:
        row = {k: item.get(k) for k in keep}
        row["integrationIds"] = sorted(row["integrationIds"] or [])
        row["layouts"] = sorted(
            ({k: lay[k] for k in ("layoutId", "sectionId", "xOffset", "yOffset", "width", "height")}
             for lay in row["layouts"] or []),
            key=lambda lay: lay["layoutId"],
        )
        rows.append(row)
    return json.dumps(sorted(rows, key=lambda r: r["id"]), sort_keys=True)


def _board(api, api_key, name):
    return api.trpc("board.getBoardByName", {"name": name}, api_key=api_key, query=True)


def sync_boards(api, api_key, spec_boards, widgets, integrations, catalog, app_ids):
    """Converge every declared board. Returns (actions, changed)."""
    actions, changed = [], False
    by_kind = {}
    for row in integrations:
        by_kind.setdefault(row["kind"], []).append(row)
    all_widgets = dict(widgets, **app_widgets(catalog, app_ids))

    for spec in spec_boards:
        name = spec["name"]
        try:
            board = _board(api, api_key, name)
        except HomarrError:
            api.trpc("board.createBoard", {
                "name": name, "columnCount": spec["columns"], "isPublic": spec["public"],
            }, api_key=api_key)
            board = _board(api, api_key, name)
            actions.append(f"created board {name}")
            changed = True

        wanted = dict(spec, widgets=spec["widgets"] + ([k for k in all_widgets if k.startswith("apps-")]
                                                       if spec.get("apps") else []))
        items, skipped = desired_items(board, wanted, all_widgets, by_kind)
        for key in skipped:
            actions.append(f"board {name}: skipped {key} (no working integration)")
        if _canonical(items) != _canonical(board.get("items") or []):
            api.trpc("board.saveBoard", {"id": board["id"], "sections": board["sections"], "items": items},
                     api_key=api_key)
            actions.append(f"saved board {name} ({len(items)} items)")
            changed = True

        if board.get("isPublic") != spec["public"]:
            api.trpc("board.changeBoardVisibility", {
                "id": board["id"], "visibility": "public" if spec["public"] else "private",
            }, api_key=api_key)
            actions.append(f"board {name} is now {'public' if spec['public'] else 'private'}")
            changed = True

        if spec.get("home"):
            current = api.trpc("serverSettings.getBoardSettings", api_key=api_key)
            if current.get("homeBoardId") != board["id"] or current.get("mobileHomeBoardId") != board["id"]:
                api.trpc("serverSettings.updateBoardSettings", {
                    "homeBoardId": board["id"], "mobileHomeBoardId": board["id"],
                }, api_key=api_key)
                actions.append(f"board {name} is the home board")
                changed = True

    return actions, changed
