"""The restic_backup role renders one backup unit per repository.

Renders the role's templates with Ansible-only filters stubbed, then checks the
unit, timer, environment file and pgpass shapes.
"""

from pathlib import Path
import re
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "restic_backup"

ENV = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
ENV.filters["comment"] = lambda text: "# " + text
ENV.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None

DEFAULTS = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
B2 = {
    "name": "b2",
    "enabled": True,
    "bucket": "example-bucket",
    "endpoint": "s3.us-example-000.backblazeb2.com",
    "access_key_id": "key-id",
    "secret_access_key": "key-secret",
    "region": "us-example-000",
}
DB = {
    "restic_backup_db_host": "db.example.test",
    "restic_backup_db_name": "appdb",
    "restic_backup_db_user": "appuser",
    "restic_backup_db_password": "pw",
}


def render(template, **extra):
    ctx = {
        **DEFAULTS,
        "ansible_managed": "managed",
        "restic_backup_name": "svc",
        "restic_backup_config_dir": "/etc/svc-backup",
        "restic_backup_password_file": "/etc/svc-backup/restic-password",
        "restic_backup_pgpass_file": "/etc/svc-backup/pgpass",
        **extra,
    }
    source = (ROLE / "templates" / template).read_text()
    return ENV.from_string(source).render(**ctx)


class ResticBackupRender(unittest.TestCase):
    def test_backup_unit_dumps_the_database_into_restic_and_prunes(self):
        unit = render("restic-backup@.service.j2", **DB)
        self.assertIn("EnvironmentFile=/etc/svc-backup/backup-%i.env", unit)
        self.assertIn("PGPASSFILE=/etc/svc-backup/pgpass", unit)
        self.assertIn("restic cat config >/dev/null 2>&1 || restic init", unit)
        self.assertIn("pg_dump -Fc appdb | restic backup --stdin --stdin-filename svc.dump", unit)
        self.assertIn("restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 24 --prune", unit)

    def test_backup_unit_without_a_database_has_no_dump_and_lists_paths(self):
        unit = render("restic-backup@.service.j2", restic_backup_paths=["/var/lib/svc"])
        self.assertNotIn("pg_dump", unit)
        self.assertNotIn("PGPASSFILE", unit)
        self.assertIn("ExecStart=/usr/bin/restic backup /var/lib/svc", unit)

    def test_timers_are_daily_and_weekly_with_catch_up(self):
        backup = render("restic-backup@.timer.j2")
        check = render("restic-check@.timer.j2")
        self.assertIn("OnCalendar=daily", backup)
        self.assertIn("OnCalendar=weekly", check)
        for timer in (backup, check):
            self.assertIn("Persistent=true", timer)
        self.assertIn("ExecStart=/usr/bin/restic check", render("restic-check@.service.j2"))

    def test_environment_file_adds_the_scheme_once_and_carries_the_key_pair(self):
        for endpoint in (B2["endpoint"], "https://" + B2["endpoint"]):
            env = render("restic-backup.env.j2", item={**B2, "endpoint": endpoint})
            self.assertIn(
                "RESTIC_REPOSITORY=s3:https://s3.us-example-000.backblazeb2.com/example-bucket",
                env,
            )
            self.assertIn("AWS_ACCESS_KEY_ID=key-id", env)
            self.assertIn("AWS_SECRET_ACCESS_KEY=key-secret", env)
            self.assertIn("AWS_DEFAULT_REGION=us-example-000", env)
            self.assertIn("RESTIC_PASSWORD_FILE=/etc/svc-backup/restic-password", env)

    def test_pgpass_escapes_colon_and_backslash_in_the_password(self):
        line = render("pgpass.j2", **{**DB, "restic_backup_db_password": "a:b\\c"}).splitlines()[-1]
        self.assertEqual(line, "db.example.test:5432:appdb:appuser:a\\:b\\\\c")

    def test_disabled_repository_timers_are_only_stopped_when_the_template_exists(self):
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        stops = [t for t in tasks if t["name"].startswith("Stop and disable")]
        self.assertEqual(len(stops), 2)
        for task in stops:
            self.assertEqual(task["when"], "restic_backup_timer_template.stat.exists")


if __name__ == "__main__":
    unittest.main()
