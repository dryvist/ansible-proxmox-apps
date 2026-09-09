"""Every fronted backend must be bounded, including the named transport.

Traefik's own defaults are a 30s dial timeout and NO response-header timeout at
all. A backend that ACCEPTS a connection and then never answers therefore makes
the ingress wait forever, and the client sees a hang rather than an error. That
is the worse failure: it reads as a network fault, and it holds a connection
per attempt.

Two transports exist and a named one does NOT inherit the default's timeouts,
so the named one is the easy thing to leave unbounded. Both are asserted here,
because a fix that covers only the default transport looks complete and leaves
the hang reachable through exactly the routes that re-encrypt to a backend.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "roles/traefik/templates/traefik.yml.j2"
DYNAMIC = ROOT / "roles/traefik/templates/dynamic.yml.j2"
DEFAULTS = ROOT / "roles/traefik/defaults/main.yml"

DIAL = "traefik_backend_dial_timeout"
HEADER = "traefik_backend_response_header_timeout"


def strip_jinja_comments(text: str) -> str:
    """Drop {# ... #} blocks so a variable named only in prose does not count."""
    return re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)


class BackendTimeouts(unittest.TestCase):
    def test_the_default_transport_bounds_both_timeouts(self) -> None:
        body = strip_jinja_comments(STATIC.read_text(encoding="utf-8"))
        self.assertIn("serversTransport:", body)
        self.assertIn("forwardingTimeouts:", body)
        self.assertIn(DIAL, body)
        self.assertIn(HEADER, body)

    def test_the_named_transport_bounds_them_too(self) -> None:
        """A named transport inherits nothing; unbounded here is unbounded."""
        body = strip_jinja_comments(DYNAMIC.read_text(encoding="utf-8"))
        self.assertIn("insecure-backend:", body)
        after = body.split("insecure-backend:", 1)[1]
        self.assertIn("forwardingTimeouts:", after)
        self.assertIn(DIAL, after)
        self.assertIn(HEADER, after)

    def test_both_timeouts_have_defaults_so_a_render_cannot_be_empty(self) -> None:
        """An undefined value renders as an empty string, which Traefik reads
        as no timeout — the very state this change removes."""
        body = DEFAULTS.read_text(encoding="utf-8")
        for name in (DIAL, HEADER):
            with self.subTest(variable=name):
                match = re.search(rf"^{name}:\s*(\S+)\s*$", body, re.MULTILINE)
                assert match is not None, f"{name} has no default"
                self.assertRegex(match.group(1), r"^\d+(ms|s|m)$")

    def test_the_response_header_timeout_is_not_tightened_into_a_new_fault(self) -> None:
        """It bounds time-to-first-header for backends that compute before
        answering. Too tight turns a slow backend into a broken one, which is a
        worse outcome than the hang being fixed."""
        body = DEFAULTS.read_text(encoding="utf-8")
        match = re.search(rf"^{HEADER}:\s*(\d+)s\s*$", body, re.MULTILINE)
        assert match is not None, "expected a value in whole seconds"
        self.assertGreaterEqual(int(match.group(1)), 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
