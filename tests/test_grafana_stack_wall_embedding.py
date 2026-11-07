"""Grafana framing is opt-in and never enables anonymous authentication."""

from pathlib import Path
from urllib.parse import urlsplit

import jinja2
from jinja2 import meta
import pytest
import yaml


ROLE = Path(__file__).resolve().parents[1] / "roles/grafana_stack"


@pytest.mark.parametrize("enabled,root_url,expected", [
    (None, "https://metrics.example.test", False),
    (False, "https://metrics.example.test", False),
    ("false", "https://metrics.example.test", False),
    (True, "https://metrics.example.test", True),
    (True, "https://wall.example.test/grafana", False),
    (True, "http://wall.example.test", True),
    (True, "https://wall.example.test:8443", True),
])
def test_embedding_requires_enabled_slides_and_different_origin(enabled, root_url, expected):
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda v: v is True or str(v).lower() == "true"
    env.filters["urlsplit"] = lambda value, part: getattr(urlsplit(value), part)
    context = {"grafana_stack_root_url": root_url, "ingress_domain": "example.test"}
    if enabled is not None:
        context["wall_grafana_slides_enabled"] = enabled
    allow = env.from_string(defaults["grafana_stack_allow_embedding"]).render(context) == "True"
    assert allow is expected

    # Render the real compose template; unrelated scalar inputs are placeholders.
    template = (ROLE / "templates/docker-compose.yml.j2").read_text()
    context: dict[str, object] = {name: "fixture" for name in meta.find_undeclared_variables(env.parse(template))}
    context.update(grafana_stack_allow_embedding=allow, grafana_stack_vm_extra_flags=[],
                   grafana_stack_provisioning_subdirs=[], grafana_stack_litellm_prices_enabled=False,
                   grafana_stack_plugins=[])
    compose = yaml.safe_load(env.from_string(template).render(context))
    settings = compose["services"]["grafana"]["environment"]
    assert settings.get("GF_SECURITY_ALLOW_EMBEDDING") == ("true" if expected else None)
    # Anonymous access is pinned off whenever framing is allowed; otherwise Grafana's default (off) applies.
    assert settings.get("GF_AUTH_ANONYMOUS_ENABLED") == ("false" if expected else None)
