"""The Homebox backup and check units give restic a cache directory.

A systemd unit has no $HOME, so without one restic runs uncached and logs a
warning on every run. Renders the role's templates with Ansible-only filters stubbed.
"""

from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROLE = Path(__file__).resolve().parents[1] / "roles" / "homebox"

ENV = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
ENV.filters["comment"] = lambda text: "# " + text
DEFAULTS = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())

CONTEXT = {
    **DEFAULTS,
    "ansible_managed": "managed",
    "homebox_config_dir": "/etc/homebox",
    "homebox_db_host": "db.example.test",
    "homebox_db_port": 5432,
    "homebox_db_user": "appuser",
    "homebox_db_name": "appdb",
    "homebox_pgpass_file": "/etc/homebox/pgpass",
    "homebox_data_dir": "/var/lib/homebox",
    "homebox_restic_keep_daily": 14,
    "homebox_restic_keep_weekly": 8,
    "homebox_restic_keep_monthly": 24,
}


class HomeboxBackupUnits(unittest.TestCase):
    def test_backup_and_check_units_set_a_restic_cache_directory(self):
        for template in ("homebox-backup@.service.j2", "homebox-check@.service.j2"):
            with self.subTest(template):
                unit = ENV.from_string((ROLE / "templates" / template).read_text()).render(**CONTEXT)
                self.assertIn("CacheDirectory=restic\n", unit)
                self.assertIn("Environment=RESTIC_CACHE_DIR=%C/restic\n", unit)


if __name__ == "__main__":
    unittest.main()
