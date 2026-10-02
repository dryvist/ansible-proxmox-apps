"""Unit test for the Homarr v2 onboarding-claim sequence in
roles/homarr/files/homarr_trpc.py.

Homarr v2.0.0 replaced the old repeatable onboard.nextStep walk with:
  - a claim cookie (POST /api/onboarding/claim) gating every onboarding call
  - a single start -> user transition, firing only from "start"
  - the claim stops authorizing calls once a user row exists, so the run
    must sign in as the just-created admin before completing "setup"
These are plain HTTP/cookie mechanics in the Homarr class itself, not
business logic over an injected fake, so the fixture below is a real (if
tiny) HTTP server -- exercising the actual cookie jar -- rather than the
duck-typed FakeApi the other homarr_api.py tests use for pure diff logic.
Confirmed against the real ghcr.io/homarr-labs/homarr:v2.0.0 image; this is
the fast, no-Docker regression guard for that same contract.
"""

import http.cookies
import importlib.util
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# homarr_trpc has no imports of its own, but load it the same way the sibling
# homarr_api.py tests do, for one consistent resolution story across this
# directory.
FILES = ROOT / "roles/homarr/files"
if str(FILES) not in sys.path:
    sys.path.insert(0, str(FILES))
SPEC = importlib.util.spec_from_file_location("homarr_trpc", FILES / "homarr_trpc.py")
assert SPEC is not None and SPEC.loader is not None
homarr_trpc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(homarr_trpc)


class _OnboardingHandler(BaseHTTPRequestHandler):
    """Mirrors homarr-labs/homarr@v2.0.0's onboarding contract: claim.ts,
    onboard-router.ts, user.ts. `require_claim` toggles per instance so one
    test can prove the claim-only-403 path without a second server."""

    require_claim = True
    # A plain class attribute (not server.state): BaseHTTPRequestHandler's
    # `server` is typed as the generic socketserver.BaseServer, so reading
    # state off it would need a narrowing override pyright rejects (mutable
    # attributes are invariant). Each handler subclass below gets its own
    # fresh dict instead.
    state: dict[str, object] = {}

    def log_message(self, format: str, *args: object) -> None:
        del format, args  # keep test output quiet

    def _cookie_token(self):
        jar = http.cookies.SimpleCookie()
        jar.load(self.headers.get("Cookie", ""))
        morsel = jar.get("homarr-onboarding-claim")
        return morsel.value if morsel else None

    def _send_json(self, code, payload, set_cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if set_cookie:
            self.send_header("Set-Cookie", f"homarr-onboarding-claim={set_cookie}; Path=/; HttpOnly")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _claimed(self):
        return self.state["claim_token"] is not None and (
            self._cookie_token() == self.state["claim_token"]
        )

    def do_POST(self):
        state = self.state
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        if self.path == "/api/onboarding/claim":
            if state["claim_token"] is None:
                state["claim_token"] = secrets.token_urlsafe(16)
                return self._send_json(200, {"status": "issued", "expiresAt": 0}, set_cookie=state["claim_token"])
            if self._claimed():
                return self._send_json(200, {"status": "active", "expiresAt": 0})
            return self._send_json(423, {"code": "locked", "expiresAt": 0})

        if self.path.startswith("/api/trpc/onboard.nextStep"):
            if self.command != "POST":
                return self._send_json(405, {"error": {"json": {"message": "method not supported"}}})
            if self.require_claim and not self._claimed():
                return self._send_json(
                    403,
                    {"error": {"json": {"message": "This onboarding session is not claimed.", "code": -32003,
                                        "data": {"code": "FORBIDDEN", "httpStatus": 403, "path": "onboard.nextStep"}}}},
                )
            if state["step"] != "start":
                return self._send_json(
                    412, {"error": {"json": {"message": "The welcome step is already complete.", "code": -32001,
                                              "data": {"code": "PRECONDITION_FAILED", "httpStatus": 412}}}},
                )
            state["step"] = "user"  # credentials-only fixture: no ldap/oidc
            return self._send_json(200, {"result": {"data": {"json": {"current": state["step"]}}}})

        if self.path.startswith("/api/trpc/onboard.currentStep"):
            return self._send_json(200, {"result": {"data": {"json": {"current": state["step"]}}}})

        if self.path.startswith("/api/trpc/user.initUser"):
            if state["step"] != "user" or not self._claimed():
                return self._send_json(
                    412, {"error": {"json": {"message": "wrong step", "code": -32001,
                                              "data": {"code": "PRECONDITION_FAILED", "httpStatus": 412}}}},
                )
            state["user_created"] = True
            state["admin_password"] = json.loads(raw)["json"]["password"]
            state["step"] = "setup"  # no ldap/oidc in this fixture
            return self._send_json(200, {"result": {"data": {"json": None}}})

        if self.path == "/api/auth/csrf":
            return self._send_json(200, {"csrfToken": "fake-csrf"})

        if self.path == "/api/auth/callback/credentials":
            form = raw.decode()
            if f"password={state.get('admin_password')}" in form.replace("%26", "&"):
                state["authed"] = True
            return self._send_json(200, {})

        if self.path == "/api/auth/session":
            if state.get("authed"):
                return self._send_json(200, {"userId": "admin"})
            return self._send_json(200, {})

        if self.path.startswith("/api/trpc/onboard.completeSetup"):
            # Gated like every onboardingProcedure: claim OR an authed admin.
            if not (self._claimed() or state.get("authed")):
                return self._send_json(
                    403,
                    {"error": {"json": {"message": "This onboarding session is not claimed.", "code": -32003,
                                        "data": {"code": "FORBIDDEN", "httpStatus": 403, "path": "onboard.completeSetup"}}}},
                )
            if state["step"] != "setup":
                return self._send_json(
                    412, {"error": {"json": {"message": "wrong step", "code": -32001,
                                              "data": {"code": "PRECONDITION_FAILED", "httpStatus": 412}}}},
                )
            payload = json.loads(raw)["json"]
            assert payload["server"]["defaultLocale"]
            assert payload["board"]["name"]
            state["setup_complete"] = True
            state["step"] = "finish"
            return self._send_json(200, {"result": {"data": {"json": None}}})

        return self._send_json(404, {"error": "not found"})

    def do_GET(self):
        return self.do_POST()


def _start_server(require_claim=True):
    # A fresh `state` dict per handler subclass (not an instance attribute):
    # BaseHTTPRequestHandler makes one handler instance per request, so the
    # state has to live on the class all those instances share.
    state: dict[str, object] = {"step": "start", "claim_token": None, "user_created": False,
                                "setup_complete": False, "authed": False}
    handler = type("Handler", (_OnboardingHandler,), {
        "require_claim": require_claim,
        "state": state,
    })
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def test_run_onboarding_completes_the_v2_claim_gated_sequence():
    server, state = _start_server()
    try:
        api = homarr_trpc.Homarr(f"http://127.0.0.1:{server.server_address[1]}")
        homarr_trpc.run_onboarding(api, "admin", "hunter2")

        assert state["step"] == "finish"
        assert state["user_created"]
        assert state["setup_complete"]
    finally:
        server.shutdown()


def test_nextstep_without_a_claim_cookie_is_refused():
    """The exact regression this guards: calling onboard.nextStep without
    first claiming the session must fail loudly, not silently misbehave."""
    server, _state = _start_server()
    try:
        api = homarr_trpc.Homarr(f"http://127.0.0.1:{server.server_address[1]}")
        try:
            api.trpc("onboard.nextStep", {})
            raise AssertionError("expected an unclaimed nextStep call to fail")
        except homarr_trpc.HomarrError as exc:
            assert "not claimed" in str(exc)
    finally:
        server.shutdown()
