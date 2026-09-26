"""roles/wall renders wall.nginx.conf.j2 with directory redirects kept relative.

Behind Traefik, an absolute redirect (scheme+host+port) for a bare directory
URL leaks the internal upstream address to the browser. `absolute_redirect
off;` is what prevents that; this guards it staying in the rendered config,
on both the server and the location that actually emits the redirect.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import jinja2

TEMPLATE = Path(__file__).resolve().parent.parent / "roles/wall/templates/wall.nginx.conf.j2"


def render(**overrides) -> str:
    env = jinja2.Environment(trim_blocks=True)
    env.filters["comment"] = lambda v: f"# {v}"
    ctx = {
        "ansible_managed": "managed",
        "wall_port": "8080",
        "wall_prometheus_host": "127.0.0.1",
        "wall_prometheus_port": "9090",
        "wall_site_dir": "/var/lib/wall/site/latest",
        "wall_config_dir": "/etc/wall",
    }
    ctx.update(overrides)
    return env.from_string(TEMPLATE.read_text()).render(**ctx)


class WallNginxConfig(unittest.TestCase):
    def test_absolute_redirect_off_present_in_server_and_location(self):
        conf = render()
        # Present at server scope (line-level default for the vhost) AND
        # restated inside `location /` (the block whose try_files fallback
        # actually generates the directory-redirect) — not relied on by
        # inheritance alone.
        self.assertEqual(conf.count("absolute_redirect off;"), 2)

        server_block, _, location_block = conf.partition("location / {")
        self.assertIn("absolute_redirect off;", server_block)
        self.assertIn("absolute_redirect off;", location_block)


if __name__ == "__main__":
    unittest.main()
