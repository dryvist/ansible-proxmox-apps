"""A failed Zammad bootstrap names its fragment, line and class, and still fails.

The bootstrap task is no_log, so the entrypoint prints one secret-free line per
failure and re-raises; the rescue prints only lines of that exact shape, then
fails the play.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app_agent_helpers import ROOT, _render, _task, _yaml

ENTRYPOINT = ROOT / "roles/zammad/files/zammad_bootstrap.rb"
BOOTSTRAP_TASKS = "roles/zammad/tasks/main/nginx_and_bootstrap.yml"
SENTINEL = "fixture-secret-message-value"


def _rescue() -> list[dict]:
    return _task(_yaml(BOOTSTRAP_TASKS), "Run the Zammad bootstrap and name the failing fragment on failure")["rescue"]


def _shown(stdout_lines: list[str]) -> list[str]:
    show = _rescue()[0]
    return _render(show["ansible.builtin.debug"]["msg"], {**show["vars"], "zammad_bootstrap": {"stdout_lines": stdout_lines}})


def _run_entrypoint(tmp_path, fragments: dict[str, str]) -> subprocess.CompletedProcess:
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("ruby is not available in this environment")
    shutil.copy(ENTRYPOINT, tmp_path / "ansible_bootstrap.rb")
    (tmp_path / "ansible_bootstrap").mkdir()
    for name, body in fragments.items():
        (tmp_path / "ansible_bootstrap" / name).write_text(body, encoding="utf-8")
    return subprocess.run(
        [ruby, str(tmp_path / "ansible_bootstrap.rb")], capture_output=True, text=True, timeout=60, check=False
    )


def test_a_raising_fragment_prints_one_message_free_line_and_still_fails(tmp_path):
    result = _run_entrypoint(
        tmp_path,
        {
            "00-ok.rb": "puts 'ZAMMAD_BOOTSTRAP_CHANGED'\n",
            "10-boom.rb": f"value = '{SENTINEL}'\n\nraise \"bad input #{{value}}\"\n",
            "20-after.rb": "puts 'AFTER'\n",
        },
    )

    assert result.returncode != 0
    assert SENTINEL not in result.stdout
    assert "AFTER" not in result.stdout
    failure_lines = [line for line in result.stdout.splitlines() if line.startswith("ZAMMAD_BOOTSTRAP_FAILED")]
    assert failure_lines == ["ZAMMAD_BOOTSTRAP_FAILED fragment=10-boom.rb line=3 class=RuntimeError"]
    assert _shown(result.stdout.splitlines()) == failure_lines


def test_a_syntax_error_fragment_is_named_and_still_fails(tmp_path):
    result = _run_entrypoint(tmp_path, {"10-broken.rb": f"x = '{SENTINEL}'\ndef (\n"})

    assert result.returncode != 0
    assert SENTINEL not in result.stdout
    assert "ZAMMAD_BOOTSTRAP_FAILED fragment=10-broken.rb line=? class=SyntaxError" in result.stdout.splitlines()


def test_the_entrypoint_prints_no_message_and_re_raises():
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    rescue_body = entrypoint.split("rescue StandardError, ScriptError => e", 1)[1].split("\n  end\n", 1)[0]
    assert "message" not in rescue_body.replace("never the message", "")
    assert "e.full_message" not in rescue_body and "e.inspect" not in rescue_body
    assert rescue_body.rstrip().endswith("raise")


def test_the_rescue_shows_only_failure_lines_then_fails():
    tasks = _yaml(BOOTSTRAP_TASKS)
    assert _task(tasks, "Run the idempotent Zammad bootstrap")["no_log"] is True
    assert _task(tasks, "Run the Zammad bootstrap and name the failing fragment on failure")["no_log"] is True

    show, fail = _rescue()
    assert show["no_log"] is False
    assert set(fail) == {"name", "no_log", "ansible.builtin.fail"}

    good = "ZAMMAD_BOOTSTRAP_FAILED fragment=20-groups-and-tokens.rb line=60 class=ActiveRecord::RecordInvalid"
    assert _shown([good]) == [good]
    assert _shown(
        [
            f"{good} {SENTINEL}",
            f"ZAMMAD_BOOTSTRAP_FAILED fragment=20-groups-and-tokens.rb line=60 class=RuntimeError: {SENTINEL}",
            f"ZAMMAD_BOOTSTRAP_FAILED {SENTINEL}",
            SENTINEL,
        ]
    ) == []
    assert _shown([]) == []
