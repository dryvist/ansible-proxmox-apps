"""Git collections are reinstalled only when their recorded ref differs.

scripts/install_galaxy_requirements.py passes --force for every git collection
on every run. The installed metadata names only the galaxy.yml version, never
the commit SHA a collection was pinned to, so the installer records the SHA it
installed and skips a collection whose record matches requirements.yml.
"""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "install_galaxy_requirements", ROOT / "scripts" / "install_galaxy_requirements.py"
)
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)

URL_A = "https://github.com/example/collection-a.git"
URL_B = "https://github.com/example/collection-b.git#/ansible/"
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40


class GitPinDecisionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pins_path = Path(self._tmp.name) / installer.GIT_PINS_FILENAME

    def tearDown(self):
        self._tmp.cleanup()

    def _write_pins(self, text):
        self.pins_path.write_text(text, encoding="utf-8")

    def test_cold_cache_reinstalls(self):
        pins = installer._load_git_pins(self.pins_path)
        self.assertEqual(pins, {})
        self.assertFalse(installer._git_collection_is_current({"name": URL_A, "version": SHA_OLD}, pins))

    def test_recorded_ref_skips(self):
        self._write_pins(json.dumps({URL_A: SHA_OLD}))
        pins = installer._load_git_pins(self.pins_path)
        self.assertTrue(installer._git_collection_is_current({"name": URL_A, "version": SHA_OLD}, pins))

    def test_changed_ref_reinstalls(self):
        self._write_pins(json.dumps({URL_A: SHA_OLD}))
        pins = installer._load_git_pins(self.pins_path)
        self.assertFalse(installer._git_collection_is_current({"name": URL_A, "version": SHA_NEW}, pins))

    def test_unrecorded_url_reinstalls(self):
        self._write_pins(json.dumps({URL_B: SHA_OLD}))
        pins = installer._load_git_pins(self.pins_path)
        self.assertFalse(installer._git_collection_is_current({"name": URL_A, "version": SHA_OLD}, pins))

    def test_entry_without_version_never_skips(self):
        self._write_pins(json.dumps({URL_A: ""}))
        pins = installer._load_git_pins(self.pins_path)
        self.assertFalse(installer._git_collection_is_current({"name": URL_A}, pins))
        self.assertFalse(installer._git_collection_is_current({"name": URL_A, "version": ""}, pins))

    def test_corrupt_pins_file_is_treated_as_cold(self):
        self._write_pins("{not json")
        self.assertEqual(installer._load_git_pins(self.pins_path), {})

    def test_non_string_pins_are_ignored(self):
        self._write_pins(json.dumps({URL_A: 1}))
        self.assertEqual(installer._load_git_pins(self.pins_path), {})


class GitPinRecordTest(unittest.TestCase):
    def test_round_trip_skips_entries_without_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / installer.GIT_PINS_FILENAME
            installer._record_git_pins(
                path,
                [
                    {"name": URL_A, "version": SHA_OLD},
                    {"name": URL_B, "version": SHA_NEW},
                    {"name": "https://example.invalid/no-version.git"},
                ],
            )
            self.assertEqual(installer._load_git_pins(path), {URL_A: SHA_OLD, URL_B: SHA_NEW})


class MainRoutesGitCollectionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.collections_root = base / "collections"
        self.work_dir = base / "work"
        self.work_dir.mkdir()
        self.pins_path = self.collections_root / installer.GIT_PINS_FILENAME
        self._old_cwd = os.getcwd()
        os.chdir(self.work_dir)
        (self.work_dir / "requirements.yml").write_text(
            yaml.safe_dump(
                {
                    "collections": [
                        {"name": URL_A, "type": "git", "version": SHA_NEW},
                        {"name": URL_B, "type": "git", "version": SHA_NEW},
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.calls = []
        self.git_requirements_seen = []
        self.failure = None
        patches = [
            mock.patch.object(installer.C, "COLLECTIONS_PATHS", [str(self.collections_root)]),
            mock.patch.object(installer, "_run", side_effect=self._recorder),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _recorder(self, *args):
        self.calls.append(args)
        if self.failure is not None:
            raise self.failure
        requirement_file = Path(args[args.index("-r") + 1])
        self.git_requirements_seen.append(yaml.safe_load(requirement_file.read_text(encoding="utf-8")))

    def _write_pins(self, pins):
        self.collections_root.mkdir(parents=True, exist_ok=True)
        self.pins_path.write_text(json.dumps(pins), encoding="utf-8")

    def _installed_names(self):
        names = []
        for call in self.git_requirements_seen:
            names.extend(item["name"] for item in call["collections"])
        return names

    def test_cold_cache_installs_every_git_collection_with_force(self):
        installer.main()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][:3], ("collection", "install", "-r"))
        self.assertEqual(self.calls[0][-1], "--force")
        self.assertEqual(sorted(self._installed_names()), sorted([URL_A, URL_B]))
        self.assertEqual(installer._load_git_pins(self.pins_path), {URL_A: SHA_NEW, URL_B: SHA_NEW})

    def test_current_pins_run_no_install(self):
        self._write_pins({URL_A: SHA_NEW, URL_B: SHA_NEW})
        installer.main()
        self.assertEqual(self.calls, [])
        self.assertEqual(installer._load_git_pins(self.pins_path), {URL_A: SHA_NEW, URL_B: SHA_NEW})

    def test_changed_ref_reinstalls_only_that_collection(self):
        self._write_pins({URL_A: SHA_OLD, URL_B: SHA_NEW})
        installer.main()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self._installed_names(), [URL_A])
        self.assertEqual(installer._load_git_pins(self.pins_path), {URL_A: SHA_NEW, URL_B: SHA_NEW})

    def test_failed_install_leaves_previous_pins_untouched(self):
        self._write_pins({URL_A: SHA_OLD})
        self.failure = subprocess.CalledProcessError(1, ["ansible-galaxy"])
        with self.assertRaises(subprocess.CalledProcessError):
            installer.main()
        self.assertEqual(installer._load_git_pins(self.pins_path), {URL_A: SHA_OLD})


if __name__ == "__main__":
    unittest.main()
