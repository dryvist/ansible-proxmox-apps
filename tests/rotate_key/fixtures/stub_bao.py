#!/usr/bin/env python3
"""Minimal stand-in for the OpenBao KV v2 + AppRole endpoints rotate-key.yml
calls. State lives in the JSON file given as argv[2] so a test case can seed
it (initial fields, version, custom_metadata) and read back what the
playbook actually wrote.

Usage: stub_bao.py <port> <state_file>
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE_FILE = sys.argv[2]


def load():
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        if self.path == "/v1/auth/approle/login":
            self._reply(200, {"auth": {"client_token": "test-token"}})
            return
        if self.path == "/v1/sys/wrapping/unwrap":
            # Single-use: a second unwrap of the same wrapping token must
            # fail, same as a real OpenBao response-wrapped secret.
            state = load()
            if state.get("wrap_used"):
                self._reply(400, {"errors": ["wrapping token is not valid or does not exist"]})
                return
            state["wrap_used"] = True
            save(state)
            self._reply(200, {"data": {"secret_id": "test-wrapped-secret-id"}})
            return
        if self.path == "/v1/secret/data/apps/test/entry":
            state = load()
            body = self._read_json()
            if int(body["options"]["cas"]) != state["version"]:
                self._reply(400, {"errors": ["cas mismatch"]})
                return
            state["data"].update(body["data"])
            state["version"] += 1
            save(state)
            self._reply(200, {"data": {"metadata": {"version": state["version"]}}})
            return
        self._reply(404, {"errors": ["unhandled path: " + self.path]})

    def do_PATCH(self):
        # RFC 7396 merge-patch, same as OpenBao's real metadata PATCH: merge
        # the given custom_metadata into what's stored, leaving every other
        # key untouched.
        if self.path == "/v1/secret/metadata/apps/test/entry":
            if self.headers.get("Content-Type") != "application/merge-patch+json":
                self._reply(400, {"errors": ["expected a merge-patch+json PATCH"]})
                return
            state = load()
            body = self._read_json()
            state["custom_metadata"].update(body.get("custom_metadata") or {})
            save(state)
            self._reply(200, {})
            return
        self._reply(404, {"errors": ["unhandled path: " + self.path]})

    def do_GET(self):
        if self.path == "/v1/secret/data/apps/test/entry":
            state = load()
            self._reply(200, {"data": {"data": state["data"], "metadata": {"version": state["version"]}}})
            return
        if self.path == "/v1/secret/metadata/apps/test/entry":
            state = load()
            self._reply(200, {"data": {"custom_metadata": state["custom_metadata"]}})
            return
        self._reply(404, {"errors": ["unhandled path: " + self.path]})

    def log_message(self, format: str, *args: object) -> None:
        del format, args  # keep test output readable


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
