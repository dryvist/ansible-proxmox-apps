"""roles/wall renders wall.nginx.conf.j2 with directory redirects kept relative.

Behind Traefik, an absolute redirect (scheme+host+port) for a bare directory
URL leaks the internal upstream address to the browser. `absolute_redirect
off;` at server scope (inherited into every location, including the
try_files fallback in `location /` that emits the redirect) is what
prevents that; this guards it staying in the rendered config.

The site also names the two upstreams the shipped gateway (wall-feed.conf)
proxies to, and the ClickHouse one is authenticated by a separately rendered
include, so both templates are rendered here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import jinja2

TEMPLATES = Path(__file__).resolve().parent.parent / "roles/wall/templates"
TEMPLATE = TEMPLATES / "wall.nginx.conf.j2"
AUTH_TEMPLATE = TEMPLATES / "wall-feed-clickhouse-auth.conf.j2"

# Fixture only; the role reads the real value from OpenBao (clickhouse-wall).
DUMMY_PASSWORD = "fixture-wall-reader-password"


def render(template: Path = TEMPLATE, **overrides) -> str:
    env = jinja2.Environment(trim_blocks=True)
    env.filters["comment"] = lambda v: f"# {v}"
    ctx = {
        "ansible_managed": "managed",
        "wall_port": "8080",
        "wall_prometheus_host": "127.0.0.1",
        "wall_prometheus_port": "9090",
        "wall_clickhouse_host": "clickhouse.test",
        "wall_clickhouse_http_port": 8123,
        "wall_clickhouse_password": DUMMY_PASSWORD,
        "wall_site_dir": "/var/lib/wall/site/latest",
        "wall_config_dir": "/etc/wall",
    }
    ctx.update(overrides)
    return env.from_string(template.read_text()).render(**ctx)


class WallNginxConfig(unittest.TestCase):
    def test_absolute_redirect_off_present_at_server_scope(self):
        conf = render()
        server_block, _, _ = conf.partition("location / {")
        self.assertIn("absolute_redirect off;", server_block)

    def test_location_root_revalidates_on_every_load(self):
        # No Cache-Control on `location /` lets browsers apply heuristic
        # freshness, so a kiosk keeps executing a stale deployed JS/CSS
        # bundle after a new release ships. `no-cache` forces revalidation
        # (a cheap 304 against the etag) on every load instead.
        conf = render()
        _, _, location_block = conf.partition("location / {")
        self.assertIn('add_header Cache-Control "no-cache" always;', location_block)

    def test_clickhouse_upstream_declared_beside_prometheus(self):
        # wall-feed.conf names both upstreams; each resolves from the
        # published inventory, never a literal in the template.
        conf = render()
        upstreams, _, _ = conf.partition("server {")
        self.assertIn("upstream prometheus {\n    server 127.0.0.1:9090;", upstreams)
        self.assertIn("upstream clickhouse {\n    server clickhouse.test:8123;", upstreams)

    def test_clickhouse_credential_lives_only_in_the_auth_include(self):
        # The site is world-readable; the credential belongs in the 0640
        # include that wall-feed.conf pulls into its ClickHouse locations.
        self.assertNotIn(DUMMY_PASSWORD, render())
        auth = render(AUTH_TEMPLATE)
        self.assertIn("proxy_set_header X-ClickHouse-User wall_reader;", auth)
        self.assertIn(f"proxy_set_header X-ClickHouse-Key {DUMMY_PASSWORD};", auth)
        self.assertNotIn("return 503;", auth)

    def test_missing_credential_answers_503_instead_of_proxying(self):
        # No fetched credential: the ClickHouse routes refuse, and no
        # header carries an empty key.
        auth = render(AUTH_TEMPLATE, wall_clickhouse_password="")
        self.assertIn("return 503;", auth)
        self.assertNotIn("proxy_set_header", auth)


if __name__ == "__main__":
    unittest.main()
