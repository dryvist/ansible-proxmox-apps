"""Contract: a plugin binary rewrite always triggers a cluster reload.

`stage_plugins.yml` copies the AWS/GitHub/OAuthapp plugin binaries onto every
voter on EVERY converge, independent of whether the declared catalog version
changed. Before this fix, the three "Reload the <X> plugin across the Raft
cluster after an upgrade" tasks fired only when `<x>_plugin_tune is changed`
-- which only happens on a version bump. A same-version binary rewrite (a
redeployed release, a corrected checksum, a re-run after an interrupted
converge) replaced the file on disk without ever reloading the already-running
plugin process, which is exactly what killed the GitHub engine's plugin
process on 2026-09-21 (its /tmp/pluginNNNN socket vanished, every GitHub
token mint returned a 500 rpc dial error).

Each reload task's `when` must now also fire on
`<x>_plugin_install_task is changed`, and each install task must register
that name so the fact exists to check.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "roles" / "openbao" / "tasks" / "main" / "stage_plugins.yml"
ENGINES = {
    "aws": ROOT / "roles" / "openbao" / "tasks" / "init" / "04-aws-engine.yml",
    "github": ROOT / "roles" / "openbao" / "tasks" / "init" / "05-github-engine.yml",
    "oauthapp": ROOT / "roles" / "openbao" / "tasks" / "init" / "06-oauth-engine.yml",
}
INSTALL_TASK_NAMES = {
    "aws": "Install the immutable AWS plugin command",
    "github": "Install the immutable GitHub plugin command",
    "oauthapp": "Install the immutable OAuthapp plugin command",
}
RELOAD_TASK_NAMES = {
    "aws": "Reload the AWS plugin across the Raft cluster after an upgrade",
    "github": "Reload the GitHub plugin across the Raft cluster after an upgrade",
    "oauthapp": "Reload the OAuthapp plugin across the Raft cluster after an upgrade",
}


def _task(path, name):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        if t.get("name") == name:
            return t
    raise AssertionError(f"task {name!r} not found in {path}")


def _when_text(task):
    when = task.get("when")
    if isinstance(when, list):
        return "\n".join(str(w) for w in when)
    return str(when)


class PluginInstallNotifiesReload(unittest.TestCase):
    def test_every_install_task_registers_a_fact(self):
        for plugin, task_name in INSTALL_TASK_NAMES.items():
            task = _task(STAGE, task_name)
            register = task.get("register")
            self.assertEqual(
                register,
                f"openbao_{plugin}_plugin_install_task",
                f"{task_name!r} must register openbao_{plugin}_plugin_install_task "
                "so the reload task's condition can reference it",
            )

    def test_every_reload_when_includes_the_install_result(self):
        for plugin, engine_path in ENGINES.items():
            task = _task(engine_path, RELOAD_TASK_NAMES[plugin])
            when_text = _when_text(task)
            expected = f"openbao_{plugin}_plugin_install_task is changed"
            self.assertIn(
                expected,
                when_text,
                f"{RELOAD_TASK_NAMES[plugin]!r} in {engine_path} must reload on "
                f"a same-version binary rewrite too, not only a version bump "
                f"(missing {expected!r} in its when:)",
            )
            # The version-bump path (the pre-existing tune condition) must
            # still be present -- this fix widens the gate, it doesn't
            # replace it.
            self.assertIn(
                f"openbao_{plugin}_plugin_tune is changed",
                when_text,
                f"{RELOAD_TASK_NAMES[plugin]!r} lost its version-bump reload condition",
            )


if __name__ == "__main__":
    unittest.main()
