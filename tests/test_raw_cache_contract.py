#!/usr/bin/env python3
"""Contract checks for the Nginx raw download cache role."""

from pathlib import Path
import re

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
    repository = next(
        task for task in tasks
        if task.get("name") == "Configure official nginx stable package repository"
    )

    assert fingerprints
    assert "573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62" in fingerprints[0]["ansible.builtin.assert"]["that"][0]
    assert repository["ansible.builtin.deb822_repository"]["install_python_debian"] is True
    assert any(task.get("ansible.builtin.systemd", {}).get("name") == "nginx" for task in tasks)


def test_raw_cache_syslog_tags_are_valid_nginx_tags():
    config = (ROLE / "templates" / "raw-cache.conf.j2").read_text()
    tags = re.findall(r"tag=([^,;\s]+)", config)

    assert tags
    assert all(re.fullmatch(r"[A-Za-z0-9_]+", tag) for tag in tags)


def test_raw_cache_key_inspection_runs_in_check_mode_once_the_key_is_on_disk():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    inspect = next(task for task in tasks if task.get("name") == "Inspect official nginx signing key")
    verify = next(task for task in tasks if task.get("name") == "Verify official nginx signing key fingerprint")
    guard = "not (ansible_check_mode and raw_cache_nginx_key_download is changed)"

    assert inspect["check_mode"] is False
    assert inspect["when"] == verify["when"] == guard


def test_raw_cache_sizes_proxy_buffers_for_release_redirect_headers():
    config = (ROLE / "templates" / "raw-cache.conf.j2").read_text()

    assert config.count("proxy_buffer_size 32k;") == 2
    assert config.count("proxy_buffers 8 32k;") == 2


def test_raw_cache_directory_belongs_to_the_nginx_worker_user():
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    directory = next(task for task in tasks if task.get("name") == "Create bounded raw_cache directory")

    assert directory["ansible.builtin.file"]["owner"] == "nginx"
    assert directory["ansible.builtin.file"]["group"] == "nginx"


def test_raw_cache_verifies_upstream_chains_up_to_depth_three():
    config = (ROLE / "templates" / "raw-cache.conf.j2").read_text()

    assert config.count("proxy_ssl_verify on;") == 2
    assert config.count("proxy_ssl_verify_depth 3;") == 2
