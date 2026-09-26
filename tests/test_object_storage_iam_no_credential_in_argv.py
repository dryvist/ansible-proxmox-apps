"""The RustFS root credential must never appear in a curl `argv` list.

`ansible.builtin.command`'s `argv:` form avoids shell interpolation, but it
does NOT hide the string from `ps aux` / `/proc/<pid>/cmdline` for the
process's lifetime -- a `-u user:pass` pair there is as exposed as it would
be on a shell command line. iam_provision_bucket_role.yml signs its RustFS
admin-API calls with curl's own --aws-sigv4, which needs the root
credential; it must reach curl via the short-lived netrc file
iam_provision.yml creates (object_storage_iam_netrc_path), never via `-u`
or any other argv element built from object_storage_root_user /
object_storage_root_password.

Loads and inspects the REAL task YAML (every `command`/`shell` task's
`argv`/`cmd`, in both this role's IAM task files and, for the same reason,
this PR's overall diff), never a reimplementation of it, so a reintroduced
`-u "{{ object_storage_root_user }}:..."` fails this test immediately.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "object_storage"
TASK_FILES = sorted((ROLE / "tasks").glob("*.yml"))

# The root credential is a user:password pair used for RustFS's admin API.
# object_storage_iam_secret_key is deliberately EXCLUDED: it travels in the
# request body via `stdin:` (add-user's JSON payload), which is not visible
# via `ps`/`/proc/<pid>/cmdline` the way argv is -- that is the correct,
# already-safe pattern, not something this test should flag. A per-bucket
# access key (not its secret) also appears in some URLs
# (add-user?accessKey=..., set-user-or-group-policy?...userOrGroup=...);
# that is the vendor's own documented API shape (the identifier, not a
# secret) and is explicitly out of scope here.
CREDENTIAL_VARS = (
    "object_storage_root_user",
    "object_storage_root_password",
)

# Only argv (command) / cmd (command or shell) are ps/procfs-visible.
# stdin, environment, and other module args are not argv and are out of
# scope for this check by design.
ARGV_FIELDS = ("argv", "cmd")


def _iter_command_tasks():
    """Yield (file, task) for every command/shell task in the role."""
    for path in TASK_FILES:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for task in loaded:
            if not isinstance(task, dict):
                continue
            for module in ("ansible.builtin.command", "ansible.builtin.shell"):
                if module in task:
                    yield path, task, module


def _flatten_strings(value):
    """Yield every string found in an argv/cmd value, however nested."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _flatten_strings(v)


class NoCredentialInArgv(unittest.TestCase):
    def test_no_command_task_carries_the_root_credential_in_argv_or_cmd(self):
        offenders = []
        for path, task, module_name in _iter_command_tasks():
            module_args = task[module_name]
            # The shell form spells its command as the module's whole
            # string/dict value; the command form's cmd/argv are keys of it.
            fields = module_args if isinstance(module_args, dict) else {"cmd": module_args}
            for field in ARGV_FIELDS:
                if field not in fields:
                    continue
                for text in _flatten_strings(fields[field]):
                    for var in CREDENTIAL_VARS:
                        if var in text:
                            offenders.append(f"{path.name}::{task.get('name')} -> {var!r} in {field}: {text!r}")
        self.assertEqual(
            offenders,
            [],
            "root credential variable(s) found in a command/shell task's "
            "argv/cmd (ps/procfs-visible for the process lifetime): " + "; ".join(offenders),
        )

    def test_the_four_admin_api_calls_use_netrc_file_not_dash_u(self):
        path = ROLE / "tasks" / "iam_provision_bucket_role.yml"
        tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
        curl_tasks = [
            t
            for t in tasks
            if isinstance(t, dict)
            and "ansible.builtin.command" in t
            and "curl" in (t["ansible.builtin.command"].get("argv") or [])
        ]
        self.assertEqual(len(curl_tasks), 4, "expected exactly 4 curl admin-API calls")
        for task in curl_tasks:
            argv = task["ansible.builtin.command"]["argv"]
            self.assertNotIn("-u", argv, f"{task['name']!r} still passes -u in argv")
            self.assertIn(
                "--netrc-file",
                argv,
                f"{task['name']!r} does not authenticate via --netrc-file",
            )


if __name__ == "__main__":
    unittest.main()
