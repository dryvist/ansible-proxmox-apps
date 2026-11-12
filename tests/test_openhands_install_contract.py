"""Agent Canvas install contract: pinned runtimes, package fetches that go
only through the site's package caches, and the uv config the service user's
uvx calls read."""

from pathlib import Path
import re
import unittest

import yaml

from app_agent_helpers import _render, _task


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "openhands"
SHARED_NODE = ROOT / "roles" / "verdaccio_cache" / "tasks" / "node_runtime.yml"

# Public package registries and installers the role must never name, so a
# cache-URL regression cannot silently fall back to a direct fetch.
PUBLIC_REGISTRIES = (
    "npmjs.org",
    "pypi.org",
    "astral.sh",
)


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _install():
    return _load(ROLE / "tasks" / "install.yml")


def _defaults():
    return _load(ROLE / "defaults" / "main.yml")


def _condition(task):
    when = task.get("when", "")
    if isinstance(when, list):
        when = " ".join(map(str, when))
    return when


class OpenHandsInstallWiring(unittest.TestCase):
    def test_main_includes_the_install_after_the_identity_tasks(self):
        tasks = _load(ROLE / "tasks" / "main.yml")
        include = _task(tasks, "Install Agent Canvas and its runtimes")
        self.assertEqual(include["ansible.builtin.include_tasks"], "install.yml")
        self.assertGreater(
            tasks.index(include),
            tasks.index(_task(tasks, "Create the OpenHands state directory")),
        )

    def test_install_fails_closed_without_the_cache_urls(self):
        guard = _task(_install(), "Require the package caches be declared")
        that = " ".join(guard["ansible.builtin.assert"]["that"])
        self.assertIn("openhands_npm_cache_url | length > 0", that)
        self.assertIn("openhands_pypi_cache_url | length > 0", that)
        self.assertIn("never fetches", guard["ansible.builtin.assert"]["fail_msg"])

    def test_cache_urls_come_from_the_published_inventory(self):
        defaults = _defaults()
        for key, cache in (
            ("openhands_npm_cache_url", "npm_cache"),
            ("openhands_pypi_cache_url", "pypi_cache"),
        ):
            expression = defaults[key]
            self.assertIn(".get('cache_proxy_urls', {})", expression)
            self.assertIn(f".get('{cache}', [])", expression)
            self.assertIn("| first | default('', true)", expression)


class OpenHandsNodeRuntime(unittest.TestCase):
    def test_defaults_pin_a_checksummed_node_24(self):
        defaults_path = (ROLE / "defaults" / "main.yml").read_text(encoding="utf-8")
        major = re.search(r"openhands_node_major:\s*(\d+)", defaults_path)
        version = re.search(r'openhands_node_version:\s*"(\d+\.\d+\.\d+)"', defaults_path)
        self.assertIsNotNone(major)
        self.assertIsNotNone(version)
        self.assertEqual(int(major.group(1)), 24)
        self.assertEqual(int(version.group(1).split(".")[0]), int(major.group(1)))
        self.assertIn("'https://nodejs.org/dist/v' ~ openhands_node_version", defaults_path)
        self.assertIn("~ '-linux-' ~ openhands_node_arch ~ '.tar.xz'", defaults_path)
        self.assertIn("'x86_64': 'x64'", defaults_path)
        self.assertIn("'aarch64': 'arm64'", defaults_path)
        digests = re.findall(r"'(?:x64|arm64)':\s*'([0-9a-f]{64})'", defaults_path)
        self.assertGreaterEqual(len(digests), 2)

    def test_node_install_reuses_the_shared_node_runtime_tasks(self):
        tasks = _install()
        include = _task(tasks, "Install the pinned Node.js runtime")
        self.assertEqual(
            include["ansible.builtin.include_role"],
            {"name": "verdaccio_cache", "tasks_from": "node_runtime"},
        )
        params = include["vars"]
        self.assertEqual(params["verdaccio_cache_node_runtime_sha256"], "{{ openhands_node_sha256 }}")
        self.assertEqual(params["verdaccio_cache_node_runtime_dir"], "{{ openhands_node_dir }}")
        self.assertEqual(params["verdaccio_cache_node_runtime_install_root"], "{{ openhands_install_dir }}")
        # Under --check the apt task above only previews, so xz-utils is not
        # really installed and the unpack must skip with it.
        register = _task(tasks, "Install the Agent Canvas runtime prerequisites")["register"]
        self.assertIn("ansible_check_mode", params["verdaccio_cache_node_runtime_skip_unpack"])
        self.assertIn(register, params["verdaccio_cache_node_runtime_skip_unpack"])
        # A first --check pass only previews the install directory too, so the
        # download is skipped rather than failing on a missing destination.
        dir_register = _task(tasks, "Create the Agent Canvas install directory")["register"]
        self.assertEqual(include["when"], f"not (ansible_check_mode and {dir_register} is changed)")

    def test_verdaccio_cache_installs_node_through_the_same_shared_tasks(self):
        verdaccio = _load(ROOT / "roles" / "verdaccio_cache" / "tasks" / "main.yml")
        include = _task(verdaccio, "Install the pinned Node.js runtime")
        self.assertEqual(include["ansible.builtin.include_tasks"], "node_runtime.yml")
        self.assertEqual(
            include["vars"]["verdaccio_cache_node_runtime_archive"].strip(),
            "/var/cache/verdaccio/node-v{{ verdaccio_cache_node_version }}"
            "-linux-{{ verdaccio_cache_node_arch }}.tar.xz",
        )

    def test_shared_node_runtime_tasks_pin_the_digest_and_unpack_once(self):
        shared = _load(SHARED_NODE)
        download = _task(shared, "Download the pinned Node.js runtime archive")
        self.assertEqual(
            download["ansible.builtin.get_url"]["checksum"], "sha256:{{ verdaccio_cache_node_runtime_sha256 }}"
        )
        unpack = _task(shared, "Install the pinned Node.js runtime")
        self.assertTrue(unpack["ansible.builtin.unarchive"]["remote_src"])
        self.assertEqual(
            unpack["ansible.builtin.unarchive"]["creates"], "{{ verdaccio_cache_node_runtime_dir }}/bin/node"
        )


class OpenHandsCanvasInstall(unittest.TestCase):
    def test_canvas_installs_the_pinned_release_through_the_npm_cache(self):
        install = _task(_install(), "Install Agent Canvas through the npm cache")
        argv = install["ansible.builtin.command"]["argv"]
        self.assertIn("@openhands/agent-canvas@{{ openhands_canvas_version }}", argv)
        self.assertIn("--registry={{ openhands_npm_cache_url }}", argv)
        self.assertIn("--global", argv)
        self.assertIn("{{ openhands_canvas_dir }}", argv)

    def test_canvas_install_has_its_own_declared_timeout(self):
        install = _task(_install(), "Install Agent Canvas through the npm cache")
        self.assertEqual(install["timeout"], "{{ openhands_canvas_install_timeout }}")
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.assertGreater(defaults["openhands_canvas_install_timeout"], 240)

    def test_canvas_reinstalls_only_when_the_pin_is_not_installed(self):
        tasks = _install()
        query = _task(tasks, "Read the installed Agent Canvas release")
        self.assertIs(query["changed_when"], False)
        self.assertIs(query["check_mode"], False)
        install = _task(tasks, "Install Agent Canvas through the npm cache")
        self.assertIs(install["changed_when"], True)
        condition = _condition(install)
        self.assertIn("_canvas_installed_version", condition)
        self.assertIn("openhands_canvas_version", condition)

    def test_installed_version_capture_matches_the_pin_as_a_string(self):
        expr = _task(_install(), "Install Agent Canvas through the npm cache")["vars"][
            "_canvas_installed_version"
        ]
        listed = "/opt/openhands/canvas/lib\n└── @openhands/agent-canvas@1.34.0\n"
        self.assertEqual(
            _render(expr, {"openhands_canvas_installed": {"stdout": listed}}).strip(), "1.34.0"
        )
        self.assertEqual(_render(expr, {"openhands_canvas_installed": {"stdout": ""}}).strip(), "")

    def test_role_never_names_a_public_registry(self):
        files = sorted(ROLE.rglob("*.yml")) + sorted(ROLE.rglob("*.j2")) + [
            ROLE / "README.md",
        ]
        self.assertGreaterEqual(len(files), 4)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for registry in PUBLIC_REGISTRIES:
                self.assertNotIn(registry, text)


class OpenHandsUvToolchain(unittest.TestCase):
    def test_uv_pin_is_renovate_tracked_and_pip_installed(self):
        defaults_path = (ROLE / "defaults" / "main.yml").read_text(encoding="utf-8")
        self.assertIn(
            "# renovate: datasource=pypi depName=uv\nopenhands_uv_version:",
            defaults_path,
        )
        install = _task(_install(), "Install uv through the PyPI cache")
        pip = install["ansible.builtin.pip"]
        self.assertEqual(pip["name"], "uv=={{ openhands_uv_version }}")
        self.assertEqual(pip["virtualenv"], "{{ openhands_uv_venv }}")
        self.assertEqual(
            pip["extra_args"], "--index-url {{ openhands_pypi_cache_url }}"
        )

    def test_uv_and_uvx_sit_on_the_default_path(self):
        expose = _task(_install(), "Expose uv and uvx on the default PATH")
        link = expose["ansible.builtin.file"]
        self.assertEqual(link["state"], "link")
        self.assertEqual(link["dest"], "/usr/local/bin/{{ item }}")
        self.assertEqual(expose["loop"], ["uv", "uvx"])

    def test_uv_config_points_the_default_index_at_the_pypi_cache(self):
        defaults = _defaults()
        self.assertEqual(
            defaults["openhands_uv_config_dir"],
            "{{ openhands_state_dir }}/.config/uv",
        )
        tasks = _install()
        directory = _task(
            tasks, "Create the uv configuration directory for the service user"
        )
        copy = _task(
            tasks, "Point the service user's uv default index at the PyPI cache"
        )["ansible.builtin.copy"]
        self.assertEqual(
            directory["ansible.builtin.file"]["path"], "{{ openhands_uv_config_dir }}"
        )
        self.assertEqual(copy["dest"], "{{ openhands_uv_config_dir }}/uv.toml")
        for owner_key in ("owner", "group"):
            self.assertEqual(copy[owner_key], "{{ openhands_user }}")
        self.assertEqual(copy["mode"], "0640")
        self.assertIn("[[index]]", copy["content"])
        self.assertIn('url = "{{ openhands_pypi_cache_url }}"', copy["content"])
        self.assertIn("default = true", copy["content"])


if __name__ == "__main__":
    unittest.main()
