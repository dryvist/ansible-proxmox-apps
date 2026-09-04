#!/usr/bin/env python3
"""Converge Homarr's admin session, API key and integrations over its own API.

Managed by Ansible (roles/homarr) — do not edit on the guest.

Why a script and not a stack of `uri` tasks: the sequence is a stateful HTTP
conversation (CSRF -> cookie -> session -> API key -> diff -> mutate) whose
every step depends on the last. Expressed as tasks it is ~250 lines of YAML
juggling cookie jars by hand; here it is one testable unit with no secret ever
touching disk or a command line — the whole spec arrives on stdin and the
result leaves on stdout.

Contract
  stdin : {"api_base","admin_username","admin_password","db_path",
           "bcrypt_module","api_key","api_key_file","force_secret_sync",
           "integrations":[...], "board":{"name","apps":[{"name","url",...}]}}
  stdout: {"changed":bool,"actions":[str],"api_key":str}
  Exit non-zero on any failure. Homarr connection-TESTS an integration before
  it will persist it, so a bad credential surfaces here as a create failure
  rather than as a silently broken tile.

Stdlib only — the guest carries no pip packages and must not need any.
"""

import json
import os
import subprocess
import sys

from homarr_trpc import (
    DEFAULT_ICON_URL,
    Homarr,
    HomarrError,
    reset_admin_password,
    run_onboarding,
    write_secret_file,
)


def _app_payload(want, icon_url):
    """Build an app body for Homarr's appManageSchema.

    Every field is `.nullable()` but NOT `.optional()`, so an omitted key is a
    validation error rather than a default — invalid_type for name/description/
    iconUrl, invalid_union for the href/pingUrl unions. Send all five, null
    rather than absent.
    """
    return {
        "name": want["name"],
        "description": want.get("desc") or None,
        "iconUrl": icon_url,
        "href": want["url"],
        "pingUrl": want.get("probe_url") or None,
    }


def sync_board(api, api_key, board_name, apps):
    """Sync one bookmark tile per catalog service onto a board.

    Two diffs, both by name/id — `app.create` and `board.addItem` always
    insert, so undiffed calls double every tile each converge. `apps` entries
    are dashboard_catalog rows as-is.

    An "app" tile points at its app row via `options.appId`, NOT via
    `addItem`'s `integrationIds` — that links to the separate `integration`
    table and 400s on an id absent from it. A bookmark carries no integration.
    """
    actions = []
    changed = False

    existing_apps = {a["name"]: a for a in api.trpc("app.all", api_key=api_key)}
    app_ids = {}
    for want in apps:
        have = existing_apps.get(want["name"])
        if have is None:
            created = api.trpc(
                "app.create", _app_payload(want, DEFAULT_ICON_URL), api_key=api_key
            )
            app_ids[want["name"]] = created["id"]
            actions.append(f"created app {want['name']}")
            changed = True
        else:
            app_ids[want["name"]] = have["id"]
            want_ping = want.get("probe_url") or None
            if have.get("href") != want["url"] or have.get("pingUrl") != want_ping:
                payload = _app_payload(want, have.get("iconUrl") or DEFAULT_ICON_URL)
                payload["id"] = have["id"]  # appEditSchema = appManageSchema & {id}
                api.trpc("app.update", payload, api_key=api_key)
                actions.append(f"updated app {want['name']}")
                changed = True

    try:
        board = api.trpc(
            "board.getBoardByName", {"name": board_name}, api_key=api_key, query=True
        )
    except HomarrError:
        # Homarr seeds its first board under a name we do not choose, so fall
        # back to whatever it actually serves as home rather than guessing one.
        try:
            board = api.trpc("board.getHomeBoard", api_key=api_key)
            actions.append(f"board {board_name!r} not found — used the home board")
        except HomarrError:
            board = None
    if not board:
        actions.append(f"board {board_name!r} does not exist — skipped tile placement")
        return actions, changed

    # Apps already tiled on this board: every "app"-kind item's own
    # options.appId, per the shape board.getBoardByName actually returns.
    on_board = {
        item["options"]["appId"]
        for item in (board.get("items") or [])
        if item.get("kind") == "app" and (item.get("options") or {}).get("appId")
    }

    for want in apps:
        app_id = app_ids[want["name"]]
        if app_id in on_board:
            continue
        # Auto-places into the board's first open section — no layout math.
        api.trpc("board.addItem", {
            "boardId": board["id"],
            "kind": "app",
            "options": {"appId": app_id},
        }, api_key=api_key)
        actions.append(f"added board tile: {want['name']}")
        changed = True

    return actions, changed


def sync_integrations(api, api_key, integrations, force_secret_sync=False):
    """Create or update each wanted integration. Returns (actions, changed)."""
    actions, changed = [], False
    existing = {row["name"]: row for row in api.trpc("integration.all", api_key=api_key)}

    # An integration whose credential did not resolve is skipped, loudly. Homarr
    # would reject it anyway (it connection-tests before persisting), and taking
    # the whole converge down because one unrelated app's key is missing helps
    # nobody. Skipping SILENTLY would be worse still — that is how a dashboard
    # ends up quietly missing half its tiles.
    wanted, skipped = [], []
    for want in integrations:
        if any(not (s.get("value") or "").strip() for s in want.get("secrets", [])):
            skipped.append(want["name"])
        else:
            wanted.append(want)
    if skipped:
        actions.append("skipped (no credential resolved): " + ", ".join(sorted(skipped)))

    for want in wanted:
        have = existing.get(want["name"])
        if have is None:
            api.trpc("integration.create", {
                "name": want["name"],
                "kind": want["kind"],
                "url": want["url"],
                "secrets": want["secrets"],
                "attemptSearchEngineCreation": False,
            }, api_key=api_key)
            actions.append(f"created {want['name']}")
            changed = True
            continue

        drifted = have.get("url") != want["url"] or have.get("kind") != want["kind"]
        if not (drifted or force_secret_sync):
            continue
        # Secrets are write-only — the API never returns them, so a rotated
        # credential is invisible here and only syncs when explicitly asked.
        #
        # appId is `.nullable()` but NOT `.optional()` in integrationUpdateSchema,
        # and update writes it straight into the row's `set` clause. Omitting it
        # is a zod 400 ("expected string, received undefined"); sending null
        # unlinks whatever app the integration points at. integration.all does
        # not carry appId — only integration.byId does — so read it back and
        # pass it through unchanged.
        linked_app = api.trpc(
            "integration.byId", {"id": have["id"]}, api_key=api_key, query=True
        ).get("app")
        api.trpc("integration.update", {
            "id": have["id"],
            "name": want["name"],
            "url": want["url"],
            "secrets": want["secrets"],
            "appId": (linked_app or {}).get("id"),
        }, api_key=api_key)
        actions.append(f"updated {want['name']}" + ("" if drifted else " (forced secret sync)"))
        changed = True

    return actions, changed


def main():
    spec = json.load(sys.stdin)
    api = Homarr(spec["api_base"])
    actions = []
    changed = False

    # Two places a usable key may already live, tried in order: OpenBao (via the
    # spec) and a 0600 file on the guest. The file matters more than it looks —
    # without it, any converge that cannot read OpenBao mints a fresh key every
    # single run, and Homarr keeps every one of them. Keys never expire, so that
    # is silent credential accumulation, not a cosmetic idempotence wart.
    key_file = spec.get("api_key_file")
    api_key = spec.get("api_key") or ""
    if not api_key and key_file and os.path.exists(key_file):
        with open(key_file, encoding="utf-8") as fh:
            api_key = fh.read().strip()

    if api_key:
        try:
            api.trpc("integration.all", api_key=api_key)
        except HomarrError:
            actions.append("stored API key rejected; minting a replacement")
            api_key = ""

    if not api_key:
        # Two ways in, and which one applies depends on state we must read
        # rather than assume:
        #
        #   Empty database  -> onboarding is still open, so create the admin
        #                      through it. This is the rebuilt-guest path.
        #   Onboarding done -> the admin exists with a password nobody
        #                      recorded. initUser is step-gated and creating a
        #                      user over the API needs the very key we are
        #                      trying to mint, so the only way back in is to
        #                      rewrite the stored hash.
        username = spec["admin_username"].strip().lower()  # usernameSchema lowercases
        if api.trpc("onboard.currentStep")["current"] != "finish":
            run_onboarding(api, username, spec["admin_password"])
            actions.append("completed onboarding and created the admin user")
            changed = True

        if not api.login(username, spec["admin_password"]):
            reset_admin_password(
                spec["db_path"], spec["bcrypt_module"], username, spec["admin_password"]
            )
            actions.append("reset the local admin password to the managed value")
            if not api.login(username, spec["admin_password"]):
                raise HomarrError("login still fails after resetting the admin password")
        api_key = api.trpc("apiKeys.create", {})["apiKey"]
        actions.append("minted an API key")
        changed = True

    if key_file:
        write_secret_file(key_file, api_key)

    int_actions, int_changed = sync_integrations(
        api, api_key, spec["integrations"], spec.get("force_secret_sync")
    )
    actions.extend(int_actions)
    changed = changed or int_changed

    board = spec.get("board") or {}
    board_apps = board.get("apps") or []
    if board_apps:
        board_actions, board_changed = sync_board(
            api, api_key, board.get("name", "default"), board_apps
        )
        actions.extend(board_actions)
        changed = changed or board_changed

    json.dump({"changed": changed, "actions": actions, "api_key": api_key}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except (HomarrError, subprocess.CalledProcessError) as exc:
        print(f"homarr_api: {exc}", file=sys.stderr)
        sys.exit(1)
