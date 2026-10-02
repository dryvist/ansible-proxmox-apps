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

    def claim_onboarding(self):
        """POST /api/onboarding/claim for the httpOnly cookie Homarr v2+
        requires before `onboard.nextStep` (an `onboardingClaimedProcedure`)
        will advance the walk. Not a tRPC call — a plain Next.js route that
        returns `{status, expiresAt}` and sets the cookie via `Set-Cookie`,
        which this instance's own cookie jar then resends automatically.

        200 means "issued" or "active" (our own token already holds it, safe
        to re-call). 423 ("locked") means a concurrent claimant holds it, and
        403/409-not-finished are the route's other refusals — all three are
        surfaced loudly rather than retried, since onboarding is meant to run
        from exactly one place. 409 "finished" alone is not an error: the
        caller only reaches here when onboarding is still open, so a `finished`
        race is backed out of silently rather than treated as a failure.
        """
        status, body = self._open(
            urllib.request.Request(
                f"{self.base}/api/onboarding/claim",
                data=b"",
                headers={"Content-Type": "application/json"},
            )
        )
        if status == 409 and json.loads(body).get("code") == "finished":
            return
        if status != 200:
            raise HomarrError(f"onboarding claim -> HTTP {status}: {body[:400]}")

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

    The steps are start -> user -> [group] -> setup -> finish (Homarr v2's
    collapsed sequence — the old per-section "import"/"settings"/
    "integrations" steps no longer exist as distinct states, so nextStep is
    now a single start -> user transition rather than a repeatable walk).

    `onboard.nextStep` requires an onboarding-claim cookie (Homarr v2+) and
    only fires from `start`; `user.initUser` is gated on `user` and itself
    advances the step — to `group` when LDAP/OIDC is enabled, else straight
    to `setup`. The `group` branch (external-auth admin group creation) has
    no exerciser here and is refused loudly rather than guessed at. `setup`
    is completed with the minimum valid payload (empty integrations/apps;
    board-tile sync happens separately, afterward, over the regular API).
    """
    api.claim_onboarding()

    if api.trpc("onboard.currentStep")["current"] == "start":
        api.trpc("onboard.nextStep")

    current = api.trpc("onboard.currentStep")["current"]
    if current == "user":
        api.trpc("user.initUser", {
            "username": username,
            "password": password,
            "confirmPassword": password,
        })
        current = api.trpc("onboard.currentStep")["current"]

    if current == "group":
        raise HomarrError(
            "onboarding reached the LDAP/OIDC 'group' step, which this "
            "converger does not drive — external-auth onboarding needs its "
            "own completion step, not yet implemented here"
        )

    if current == "setup":
        api.trpc("onboard.completeSetup", {
            "server": {"defaultLocale": "en", "defaultColorScheme": "light"},
            "board": {
                "name": "home",
                "primaryColor": "#1971c2",
                "secondaryColor": "#1c7ed6",
                "itemRadius": "md",
            },
        })
        current = api.trpc("onboard.currentStep")["current"]

    if current != "finish":
        raise HomarrError(f"onboarding stalled at step {current!r} instead of reaching 'finish'")


