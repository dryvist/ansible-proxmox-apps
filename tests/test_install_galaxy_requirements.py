"""Git collections are reinstalled only when their recorded ref or directory is missing.

scripts/install_galaxy_requirements.py passes --force for each stale git
collection. The installed metadata names only the galaxy.yml version, never the
commit SHA a collection was pinned to, so the installer records the SHA and the
installed directory it reported. A collection is skipped only when the record
matches requirements.yml and that directory still exists.
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
FQCN_A = "testns.alpha"
FQCN_B = "testns.beta"
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40


def _entry(sha, fqcn):
    namespace, name = fqcn.split(".", 1)
    return {"ref": sha, "path": f"ansible_collections/{namespace}/{name}"}


def _install_dir(root, fqcn):
    namespace, name = fqcn.split(".", 1)
    return root / "ansible_collections" / namespace / name


class GitPinDecisionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pins_path = self.root / installer.GIT_PINS_FILENAME

    def tearDown(self):
        self._tmp.cleanup()

    def _write_pins(self, pins):
        self.pins_path.write_text(json.dumps(pins), encoding="utf-8")

    def _current(self, requirement):
        pins = installer._load_git_pins(self.pins_path)
        return installer._git_collection_is_current(requirement, pins, self.root)

    def test_cold_cache_reinstalls(self):
        self.assertEqual(installer._load_git_pins(self.pins_path), {})
        self.assertFalse(self._current({"name": URL_A, "version": SHA_OLD}))

    def test_recorded_ref_with_directory_skips(self):
        self._write_pins({URL_A: _entry(SHA_OLD, FQCN_A)})
        _install_dir(self.root, FQCN_A).mkdir(parents=True)
        self.assertTrue(self._current({"name": URL_A, "version": SHA_OLD}))

    def test_recorded_ref_without_directory_reinstalls(self):
        self._write_pins({URL_A: _entry(SHA_OLD, FQCN_A)})
        self.assertFalse(self._current({"name": URL_A, "version": SHA_OLD}))

    def test_changed_ref_reinstalls(self):
        self._write_pins({URL_A: _entry(SHA_OLD, FQCN_A)})
        _install_dir(self.root, FQCN_A).mkdir(parents=True)
        self.assertFalse(self._current({"name": URL_A, "version": SHA_NEW}))

    def test_unrecorded_url_reinstalls(self):
        self._write_pins({URL_B: _entry(SHA_OLD, FQCN_B)})
        _install_dir(self.root, FQCN_B).mkdir(parents=True)
        self.assertFalse(self._current({"name": URL_A, "version": SHA_OLD}))

    def test_entry_without_version_never_skips(self):
        self._write_pins({URL_A: _entry("", FQCN_A)})
        _install_dir(self.root, FQCN_A).mkdir(parents=True)
        self.assertFalse(self._current({"name": URL_A}))
        self.assertFalse(self._current({"name": URL_A, "version": ""}))

    def test_corrupt_pins_file_is_treated_as_cold(self):
        self.pins_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(installer._load_git_pins(self.pins_path), {})

    def test_malformed_entry_discards_the_whole_record(self):
        self._write_pins({URL_A: _entry(SHA_OLD, FQCN_A), URL_B: "a" * 40})
        self.assertEqual(installer._load_git_pins(self.pins_path), {})

    def test_install_path_is_recorded_only_when_it_matches_the_root(self):
        root = self.root
        reported = root / "ansible_collections" / "testns" / "alpha"
        output = f"Installing 'testns.alpha:1.0.0' to '{reported}'\n"
        self.assertEqual(installer._installed_collection_path(output, root), "ansible_collections/testns/alpha")
        elsewhere = self.root / "elsewhere" / "ansible_collections" / "testns" / "alpha"
        other_output = f"Installing 'testns.alpha:1.0.0' to '{elsewhere}'\n"
        self.assertIsNone(installer._installed_collection_path(other_output, root))
        self.assertIsNone(installer._installed_collection_path("nothing installed here", root))


class GitPinRecordTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / installer.GIT_PINS_FILENAME
            pins = {URL_A: _entry(SHA_OLD, FQCN_A), URL_B: _entry(SHA_NEW, FQCN_B)}
            installer._write_git_pins(path, pins)
            self.assertEqual(installer._load_git_pins(path), pins)


class MainRoutesGitCollectionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.collections_root = base / "collections"
        self.work_dir = base / "work"
        self.work_dir.mkdir()
        self.pins_path = self.collections_root / installer.GIT_PINS_FILENAME
        self.fqcn_by_url = {URL_A: FQCN_A, URL_B: FQCN_B}
        self.report_install = True
        self.failure = None
        self.installs = []
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
        for patch in (
            mock.patch.object(installer.C, "COLLECTIONS_PATHS", [str(self.collections_root)]),
            mock.patch.object(installer, "_run", side_effect=self._recorder),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _recorder(self, *args):
        if self.failure is not None:
            self.installs.append(None)
            raise self.failure
        requirement_file = Path(args[args.index("-r") + 1])
        url = yaml.safe_load(requirement_file.read_text(encoding="utf-8"))["collections"][0]["name"]
        self.installs.append(url)
        fqcn = self.fqcn_by_url[url]
        target = _install_dir(self.collections_root, fqcn)
        target.mkdir(parents=True, exist_ok=True)
        if not self.report_install:
            return ""
        return f"Installing '{fqcn}:1.0.0' to '{target}'\n"

    def _write_pins(self, pins):
        self.collections_root.mkdir(parents=True, exist_ok=True)
        self.pins_path.write_text(json.dumps(pins), encoding="utf-8")

    def _make_install_dir(self, fqcn):
        _install_dir(self.collections_root, fqcn).mkdir(parents=True, exist_ok=True)

    def _recorded(self):
        return installer._load_git_pins(self.pins_path)

    def test_cold_cache_installs_each_git_collection_with_force(self):
        installer.main()
        self.assertEqual(sorted(self.installs), sorted([URL_A, URL_B]))
        self.assertEqual(
            self._recorded(),
            {URL_A: _entry(SHA_NEW, FQCN_A), URL_B: _entry(SHA_NEW, FQCN_B)},
        )

    def test_current_pins_and_directories_run_no_install(self):
        self._write_pins({URL_A: _entry(SHA_NEW, FQCN_A), URL_B: _entry(SHA_NEW, FQCN_B)})
        self._make_install_dir(FQCN_A)
        self._make_install_dir(FQCN_B)
        installer.main()
        self.assertEqual(self.installs, [])
        self.assertEqual(
            self._recorded(),
            {URL_A: _entry(SHA_NEW, FQCN_A), URL_B: _entry(SHA_NEW, FQCN_B)},
        )

    def test_missing_directory_reinstalls_only_that_collection(self):
        self._write_pins({URL_A: _entry(SHA_NEW, FQCN_A), URL_B: _entry(SHA_NEW, FQCN_B)})
        self._make_install_dir(FQCN_A)
        installer.main()
        self.assertEqual(self.installs, [URL_B])
        self.assertEqual(self._recorded()[URL_B], _entry(SHA_NEW, FQCN_B))

    def test_changed_ref_reinstalls_only_that_collection(self):
        self._write_pins({URL_A: _entry(SHA_OLD, FQCN_A), URL_B: _entry(SHA_NEW, FQCN_B)})
        self._make_install_dir(FQCN_A)
        self._make_install_dir(FQCN_B)
        installer.main()
        self.assertEqual(self.installs, [URL_A])
        self.assertEqual(self._recorded()[URL_A], _entry(SHA_NEW, FQCN_A))

    def test_failed_install_leaves_previous_record_untouched(self):
        self._write_pins({URL_A: _entry(SHA_OLD, FQCN_A)})
        self._make_install_dir(FQCN_A)
        self.failure = subprocess.CalledProcessError(1, ["ansible-galaxy"])
        with self.assertRaises(subprocess.CalledProcessError):
            installer.main()
        self.assertEqual(self._recorded(), {URL_A: _entry(SHA_OLD, FQCN_A)})

    def test_install_without_reported_path_stays_unrecorded(self):
        self.report_install = False
        installer.main()
        self.assertEqual(self._recorded(), {})
        self.report_install = True
        self.installs.clear()
        installer.main()
        self.assertEqual(sorted(self.installs), sorted([URL_A, URL_B]))


if __name__ == "__main__":
    unittest.main()
