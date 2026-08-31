#!/usr/bin/env python3
"""Homarr's HTTP surface: the tRPC client, login, and admin-password recovery.

Managed by Ansible (roles/homarr) -- do not edit on the guest. Imported by the
`homarr-api` entrypoint that sits beside it; both files are deployed into the
same directory so Python's own sys.path[0] resolves this import with no
packaging, no PYTHONPATH and no install step.

Split out of homarr_api.py because that file reached the repo's per-file token
ceiling. The seam is deliberate: everything here is about TALKING to Homarr,
and everything left in the entrypoint is about deciding WHAT to converge.

Stdlib only — the guest carries no pip packages and must not need any.
"""

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


class HomarrError(RuntimeError):
    pass


# iconUrl is zod min(1), so a bookmark tile with no icon still needs SOME
# string. An inline SVG avoids depending on an external icon host.
DEFAULT_ICON_URL = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "viewBox='0 0 24 24'%3E%3C/svg%3E"
)

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

    def trpc(self, procedure, payload=None, api_key=None, query=False):
        """Call a tRPC procedure. Homarr sets a superjson transformer, so every
        body and every response is wrapped in a top-level "json" key.

        `query=True` marks a tRPC query: those are served over GET and reject
        a POST, so an input-bearing one passes its argument in the `input`
        query string. A query with no input needs no flag — urllib already
        sends GET when there is no body.
        """
        url = f"{self.base}/api/trpc/{procedure}"
        headers = {"Content-Type": "application/json"}
        if api_key:
            # Homarr's own header. NOT `Authorization: Bearer` — the published
            # API reference is wrong about that and a Bearer token 401s.
            headers["ApiKey"] = api_key
        data = None
        if payload is not None:
            if query:
                url += "?input=" + urllib.parse.quote(json.dumps({"json": payload}))
            else:
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


