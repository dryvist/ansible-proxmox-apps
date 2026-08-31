"""Every connection option in ansible.cfg must be one some plugin declares.

A setting no plugin reads is silently inert: it looks like a tuning decision,
it survives review, and it misleads whoever reads it next. Two were found here
at once -- `[proxmox_pct_remote_connection] pipelining = False`, against a
plugin that declares no pipelining option at all, and an `ansible_module_utils`
var that is not an Ansible variable in the first place. Both had confident
comments explaining behaviour they never produced.

This checks the general case rather than denylisting those two: for every
`[<something>_connection]` section in ansible.cfg, some installed connection
plugin must declare that exact ini section+key.
"""

import configparser
import os
from pathlib import Path
import re
import unittest

import ansible
import yaml


ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "ansible.cfg"


DOC_RE = re.compile(r"^DOCUMENTATION\s*=\s*r?['\"]{3}(.*?)['\"]{3}", re.S | re.M)


def declared_connection_ini_options():
    """Every (section, key) any installed connection plugin reads from ini.

    Read straight out of each plugin's DOCUMENTATION block. Ansible's own doc
    helpers move between releases; the plugin file does not.

    Scans ansible-core AND installed collections. An earlier version used
    connection_loader.all(), which missed the collection plugin this repo
    actually connects with -- and then flagged that plugin's own real option
    as dead config. A checker that reports correct configuration as wrong is
    worse than no checker.
    """
    declared = set()
    for source_file in _connection_plugin_files():
        try:
            source = source_file.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 - unreadable plugin tells us nothing
            continue
        match = DOC_RE.search(source)
        if not match:
            continue
        try:
            docs = yaml.safe_load(match.group(1))
        except Exception:  # noqa: BLE001
            continue
        for option in (docs or {}).get("options", {}).values():
            for entry in (option or {}).get("ini", []) or []:
                if isinstance(entry, dict) and entry.get("section") and entry.get("key"):
                    declared.add((entry["section"], entry["key"]))
    return declared


def _connection_plugin_files():
    roots = [Path(ansible.__file__).parent / "plugins" / "connection"]
    collections = os.environ.get("ANSIBLE_COLLECTIONS_PATH") or str(
        Path.home() / ".ansible" / "collections"
    )
    for root in collections.split(os.pathsep):
        roots.extend(Path(root).glob("ansible_collections/*/*/plugins/connection"))
    for root in roots:
        if root.is_dir():
            yield from root.glob("*.py")


class ConnectionOptionsAreReal(unittest.TestCase):
    def setUp(self):
        parser = configparser.ConfigParser()
        parser.read(CFG)
        self.parser = parser
        self.declared = declared_connection_ini_options()

    def test_the_probe_itself_found_options(self):
        # Positive control: if plugin introspection silently returned nothing,
        # every assertion below would pass vacuously.
        self.assertGreater(
            len(self.declared), 20,
            "no connection options discovered -- the check would pass vacuously",
        )
        self.assertIn(("ssh_connection", "pipelining"), self.declared)

    def test_collection_connection_plugins_are_scanned(self):
        # The plugin this repo actually connects LXC guests with lives in a
        # collection, not ansible-core. Missing those made the checker flag a
        # real option as dead config; without this the regression is silent.
        self.assertIn(
            ("paramiko_connection", "pty"), self.declared,
            "collection connection plugins were not scanned",
        )

    def test_every_connection_option_set_here_is_read_by_some_plugin(self):
        orphans = []
        for section in self.parser.sections():
            if not section.endswith("_connection"):
                continue
            for key in self.parser.options(section):
                if (section, key) not in self.declared:
                    orphans.append(f"[{section}] {key}")
        self.assertEqual(
            orphans, [],
            "ansible.cfg sets connection options no installed plugin reads; "
            "they are inert and will mislead the next reader: "
            + ", ".join(orphans),
        )


if __name__ == "__main__":
    unittest.main()
