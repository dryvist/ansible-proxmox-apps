#!/usr/bin/env python3
"""Contract checks for the Nginx raw download cache role."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "roles" / "raw_cache"


def test_raw_cache_defaults_pin_nginx_and_configure_the_required_origins():
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())

    assert defaults["raw_cache_nginx_version"] == "1.30.6"
    assert defaults["raw_cache_port"] == 8080
    assert defaults["raw_cache_cache_max_size"] == "20g"
    assert defaults["raw_cache_upstreams"] == [
        {"name": "github_raw", "upstream": "https://raw.githubusercontent.com"},
        {"name": "github_releases", "upstream": "https://github.com"},
        {"name": "hermes_assets", "upstream": "https://hermes-assets.nousresearch.com"},
    ]


def test_raw_cache_follows_https_redirects_and_uses_the_origin_url_cache_key():
    config = (ROLE / "templates" / "raw-cache.conf.j2").read_text()
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())

    assert "proxy_cache_path {{ raw_cache_cache_dir }}" in config
    assert "max_size={{ raw_cache_cache_max_size }}" in config
    assert "map $request_uri $raw_cache_request_url {" in config
    assert "~^/{{ item.name }}(/.*)$ {{ item.upstream | regex_replace('/+$', '') }}$1;" in config
    assert config.index("map $request_uri $raw_cache_request_url {") < config.index("rewrite ^/{{ item.name }}/")
    assert "$uri$is_args$args" not in config
    assert "proxy_cache_key $raw_cache_request_url;" in config
    assert "proxy_pass $raw_cache_redirect_url;" in config
    assert "error_page 301 302 303 307 308 = @raw_cache_follow;" in config
    assert any(task.get("name") == "Check raw_cache health endpoint" for task in tasks)


def test_raw_cache_is_native_nginx_and_checks_the_repository_key():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    fingerprints = [task for task in tasks if task.get("name") == "Verify official nginx signing key fingerprint"]

    assert fingerprints
    assert "573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62" in fingerprints[0]["ansible.builtin.assert"]["that"][0]
    assert any(task.get("ansible.builtin.systemd", {}).get("name") == "nginx" for task in tasks)
