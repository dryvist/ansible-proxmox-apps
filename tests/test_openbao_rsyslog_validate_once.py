# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""rsyslog is validated once, after every drop-in writer has run.

audit.yml and secret_age.yml each write a rsyslog.d drop-in that can load
imfile. A `rsyslogd -N1` placed inside audit.yml validated the assembled
config before secret_age.yml had rewritten its drop-in, so a drop-in from
before the imfile guard failed validation first, the play was isolated, and
the task that would have repaired it never ran on any later converge either.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/openbao/tasks"
VALIDATE = "Validate the full rsyslog configuration"


def _names(path):
    return [t.get("name", "") for t in yaml.safe_load(path.read_text(encoding="utf-8"))]


class RsyslogValidatedOnceAfterAllWriters(unittest.TestCase):
    def test_no_drop_in_writer_validates_the_whole_config_itself(self):
        for fragment in ("audit.yml", "secret_age.yml"):
            self.assertFalse(
                [n for n in _names(TASKS / fragment) if n.startswith(VALIDATE)],
                f"{fragment} validates rsyslog before the other writer has run",
            )

    def test_validation_follows_the_last_drop_in_include(self):
        names = _names(TASKS / "main/configure_and_bootstrap.yml")
        self.assertGreater(
            names.index(VALIDATE),
            names.index("Deploy the secret-age auditor timer"),
        )
        self.assertGreater(
            names.index(VALIDATE),
            names.index("Enable the audit device and ship the audit log"),
        )
        self.assertEqual(names.count(VALIDATE), 1)


if __name__ == "__main__":
    unittest.main()
