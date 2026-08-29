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
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


class HomarrError(RuntimeError):
    pass


# Homarr's app schema requires a non-empty iconUrl (zod min(1)) — a plain
# bookmark tile with no icon opinion still needs SOME string. A tiny inline
# SVG avoids depending on an external icon host or Homarr's own icon search
# resolving a match for every service name.
DEFAULT_ICON_URL = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24'%3E%3C/svg%3E"
)


def _app_payload(want, icon_url):
    """Build an app body for Homarr's appManageSchema.

    Every field there is `.nullable()` but NOT `.optional()`, so a missing key
    is a validation error, not a default: name/description/iconUrl fail as
    invalid_type, and href/pingUrl as invalid_union (they are
    `.or(z.literal(""))` unions). Send all five explicitly, null rather than
    omitted, or app.create 400s.
    """
    return {
        "name": want["name"],
        "description": want.get("desc") or None,
        "iconUrl": icon_url,
        "href": want["url"],
        "pingUrl": None,
    }


class Homarr:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _open(self, req):
        try:
            with self.opener.open(req, timeout=60) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def trpc(self, procedure, payload=None, api_key=None):
        """Call a tRPC procedure. Homarr sets a superjson transformer, so every
        body and every response is wrapped in a top-level "json" key."""
        url = f"{self.base}/api/trpc/{procedure}"
        headers = {"Content-Type": "application/json"}
        if api_key:
            # Homarr's own header. NOT `Authorization: Bearer` — the published
            # API reference is wrong about that and a Bearer token 401s.
            headers["ApiKey"] = api_key
        data = None
        if payload is not None:
            data = json.dumps({"json": payload}).encode()
        status, body = self._open(
            urllib.request.Request(url, data=data, headers=headers)
        )
        if status != 200:
            raise HomarrError(f"{procedure} -> HTTP {status}: {body[:400]}")
        try:
            return json.loads(body)["result"]["data"]["json"]
        except (ValueError, KeyError) as exc:
            # The failure this whole role exists to prevent: an HTML login page
            # parsed as JSON. Name it explicitly so it is never re-diagnosed.
            hint = ""
            if body.lstrip().startswith("<"):
                hint = (
                    " — got HTML, not JSON. Something is intercepting this "
                    "request (an SSO gate in front of the API?). Ansible must "
                    "address Homarr directly, never through the fronted vhost."
                )
            raise HomarrError(f"{procedure} returned unparseable body{hint}: {body[:200]}") from exc

    def login(self, username, password):
        """NextAuth credentials sign-in. Returns True when a session results."""
        self.jar.clear()
        status, body = self._open(urllib.request.Request(f"{self.base}/api/auth/csrf"))
        if status != 200:
            raise HomarrError(f"csrf -> HTTP {status}")
        csrf = json.loads(body)["csrfToken"]
        form = urllib.parse.urlencode(
            {
                "csrfToken": csrf,
                "name": username,
                "password": password,
                "redirect": "false",
                "json": "true",
            }
        ).encode()
        self._open(
            urllib.request.Request(
                f"{self.base}/api/auth/callback/credentials",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        )
        status, body = self._open(urllib.request.Request(f"{self.base}/api/auth/session"))
        return status == 200 and bool(body.strip()) and "userId" in body


def reset_admin_password(db_path, bcrypt_module, username, password):
    """Rewrite the admin's bcrypt hash to a known value.

    Needed because onboarding is one-shot: once `onboarding.step` is `finish`,
    `user.initUser` refuses to run and `POST /api/users` requires the very API
    key we cannot mint without a session. On a guest whose admin password was
    set by hand in the UI there is otherwise no way back in. Hashing uses
    Homarr's OWN bundled bcrypt so the cost and prefix always match what its
    verifier expects.
    """
    script = (
        "const bcrypt=require(process.argv[1]);"
        "process.stdout.write(bcrypt.hashSync(process.env.HOMARR_PW,10));"
    )
    digest = subprocess.run(
        ["node", "-e", script, bcrypt_module],
        check=True,
        capture_output=True,
        text=True,
        env={"HOMARR_PW": password, "PATH": "/usr/bin:/bin:/usr/local/bin"},
    ).stdout.strip()

    import sqlite3

    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.execute(
            "UPDATE user SET password = ?, provider = ? WHERE name = ?",
            (digest, "credentials", username),
        )
        conn.commit()
        if conn.total_changes < 1:
            raise HomarrError(f"no user row named {username!r} to reset")
    finally:
        conn.close()


def write_secret_file(path, value):
    """Persist a credential 0600, creating the directory if needed."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")


def run_onboarding(api, username, password):
    """Drive a fresh instance through onboarding to a usable admin account.

    The steps are start -> import -> user -> group -> settings -> integrations
    -> finish. `onboard.nextStep` is public and advances one step at a time,
    and `user.initUser` is gated on the DB currently sitting at `user` — so the
    walk is: advance to `user`, create the admin, then advance to `finish`.

    Bounded rather than `while True`: a step that stops advancing (an upstream
    change to the sequence, say) must fail loudly here instead of spinning.
    """

    def walk_to(target):
        for _ in range(len(ONBOARDING_STEPS) + 1):
            if api.trpc("onboard.currentStep")["current"] == target:
                return
            api.trpc("onboard.nextStep", {"preferredStep": target})
        raise HomarrError(f"onboarding never reached the {target!r} step")

    walk_to("user")
    api.trpc("user.initUser", {
        "username": username,
        "password": password,
        "confirmPassword": password,
    })
    walk_to("finish")


ONBOARDING_STEPS = (
    "start", "import", "user", "group", "settings", "integrations", "finish",
)


def sync_board(api, api_key, board_name, apps):
    """Sync one bookmark tile per catalog service onto a board.

    Two diffs, both by NAME/id — Homarr's `app.create` and `board.addItem`
    always insert, so calling either undiffed doubles every tile on every
    converge. `apps` entries are dashboard_catalog rows as-is (name/url/desc),
    passed through unrenamed rather than reshaped in Jinja first.

    A board tile (widget kind "app") points at an `app` row through its own
    `options.appId` field, NOT through `board.addItem`'s `integrationIds` —
    that field links to the separate `integration` table (Sonarr, Radarr, the
    kind already converged above) and `addItem` 400s if given an id it cannot
    find there. A plain bookmark tile carries no integration at all.
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
            if have.get("href") != want["url"]:
                payload = _app_payload(want, have.get("iconUrl") or DEFAULT_ICON_URL)
                payload["id"] = have["id"]  # appEditSchema = appManageSchema & {id}
                api.trpc("app.update", payload, api_key=api_key)
                actions.append(f"updated app {want['name']}")
                changed = True

    try:
        board = api.trpc("board.getBoardByName", {"name": board_name}, api_key=api_key)
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

    existing = {row["name"]: row for row in api.trpc("integration.all", api_key=api_key)}

    # An integration whose credential did not resolve is skipped, loudly. Homarr
    # would reject it anyway (it connection-tests before persisting), and taking
    # the whole converge down because one unrelated app's key is missing helps
    # nobody. Skipping SILENTLY would be worse still — that is how a dashboard
    # ends up quietly missing half its tiles.
    wanted, skipped = [], []
    for want in spec["integrations"]:
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
        if not (drifted or spec.get("force_secret_sync")):
            continue
        # Secrets are write-only — the API never returns them, so a rotated
        # credential is invisible here and only syncs when explicitly asked.
        api.trpc("integration.update", {
            "id": have["id"],
            "name": want["name"],
            "url": want["url"],
            "secrets": want["secrets"],
        }, api_key=api_key)
        actions.append(f"updated {want['name']}" + ("" if drifted else " (forced secret sync)"))
        changed = True

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
