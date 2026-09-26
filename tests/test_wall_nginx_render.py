"""roles/wall renders wall.nginx.conf.j2 with directory redirects kept relative.

Behind Traefik, an absolute redirect (scheme+host+port) for a bare directory
URL leaks the internal upstream address to the browser. `absolute_redirect
off;` at server scope (inherited into every location, including the
try_files fallback in `location /` that emits the redirect) is what
prevents that; this guards it staying in the rendered config.
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
    def test_absolute_redirect_off_present_at_server_scope(self):
        conf = render()
        server_block, _, _location_block = conf.partition("location / {")
        self.assertIn("absolute_redirect off;", server_block)


if __name__ == "__main__":
    unittest.main()
