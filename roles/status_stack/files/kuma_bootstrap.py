#!/usr/bin/env python3
"""Bootstrap Uptime Kuma admin + keystone HTTP monitors via its Socket.IO API.

Managed by Ansible (roles/status_stack). Stdlib + the `socketio` / `requests`
packages are NOT assumed on the guest — this script speaks the minimal HTTP
setup endpoint, then best-effort monitor creation. If Socket.IO client libs
are absent, admin setup still succeeds and monitors are skipped with a clear
stdout action (Gatus already covers the same keystone URLs).

Contract
  stdin : {"base_url","username","password","interval_seconds","monitors":[{"name","url"}]}
  stdout: {"changed":bool,"actions":[str]}
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def _http_json(method, url, body=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        return exc.code, payload


def main():
    spec = json.load(sys.stdin)
    base = spec["base_url"].rstrip("/")
    user = spec["username"]
    password = spec["password"]
    interval = int(spec.get("interval_seconds", 60))
    monitors = spec.get("monitors") or []
    actions = []
    changed = False

    # Need-setup probe (Uptime Kuma exposes this on the entry page).
    status, entry = _http_json("GET", f"{base}/api/entry-page")
    need_setup = bool(entry.get("needSetup")) if status == 200 else True

    if need_setup:
        status, result = _http_json(
            "POST",
            f"{base}/setup",
            {"username": user, "password": password},
        )
        if status not in (200, 201) and not result.get("ok", False):
            # Older builds return plain text; treat 2xx as success.
            if status < 200 or status >= 300:
                print(
                    json.dumps(
                        {
                            "changed": False,
                            "actions": actions,
                            "error": f"setup failed status={status} body={result}",
                        }
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
        actions.append("created admin via /setup")
        changed = True
    else:
        actions.append("admin already configured")

    # Monitor sync via Socket.IO needs a client library. Prefer skipping rather
    # than inventing a fragile protocol — Gatus keystone group is the SoR.
    try:
        import socketio  # type: ignore
    except ImportError:
        actions.append(
            f"skipped {len(monitors)} keystone monitors (python-socketio absent; "
            "Gatus keystone group covers the same URLs)"
        )
        json.dump({"changed": changed, "actions": actions}, sys.stdout)
        print()
        return

    sio = socketio.Client(reconnection=False)
    try:
        sio.connect(f"{base}/", transports=["websocket", "polling"], wait_timeout=20)
        # Login
        login_ok = False

        def _login_cb(result):
            nonlocal login_ok
            login_ok = bool(result and result.get("ok"))

        sio.emit("login", {"username": user, "password": password, "token": ""}, callback=_login_cb)
        sio.sleep(2)
        if not login_ok:
            # token-less older API
            sio.emit("login", {"username": user, "password": password})
            sio.sleep(2)

        existing = {}

        def _monitors_cb(result):
            if isinstance(result, dict):
                for mid, mon in result.items():
                    if isinstance(mon, dict) and mon.get("name"):
                        existing[mon["name"]] = mon

        sio.emit("getMonitorList", callback=_monitors_cb)
        sio.sleep(2)

        for mon in monitors:
            name = mon["name"]
            url = mon["url"]
            if name in existing:
                actions.append(f"monitor exists: {name}")
                continue
            payload = {
                "type": "http",
                "name": name,
                "url": url,
                "method": "GET",
                "interval": interval,
                "retryInterval": interval,
                "maxretries": 1,
                "expiryNotification": False,
                "ignoreTls": False,
                "maxredirects": 10,
                "accepted_statuscodes": ["200-399"],
                "notificationIDList": {},
            }
            added = {"ok": False}

            def _add_cb(result):
                added["ok"] = bool(result and result.get("ok"))

            sio.emit("add", payload, callback=_add_cb)
            sio.sleep(2)
            if added["ok"]:
                actions.append(f"added monitor: {name}")
                changed = True
            else:
                actions.append(f"add monitor failed or unconfirmed: {name}")
    finally:
        try:
            sio.disconnect()
        except Exception:
            pass

    json.dump({"changed": changed, "actions": actions}, sys.stdout)
    print()


if __name__ == "__main__":
    main()
