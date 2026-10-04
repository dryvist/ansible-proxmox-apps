"""Fail-closed selection and restart behavior for the ZCode queue feeder."""

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "roles"
    / "agent_sandbox"
    / "files"
    / "zcode_feeder.py"
)
SPEC = importlib.util.spec_from_file_location("zcode_feeder", MODULE_PATH)
feeder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(feeder)


def queue_task(
    *, task_id=1, manifest=None, labels=None, assignees=None, done=False, description=None
):
    manifest = manifest or {
        "schema": 1,
        "tool": "zcode",
        "kind": "coding",
        "sensitive": False,
        "repo": "dryvist/example",
        "prompt": "Add a regression test.",
    }
    return {
        "id": task_id,
        "created": f"2026-10-03T00:00:{task_id:02d}Z",
        "description": description if description is not None else f"<p>{json.dumps(manifest)}</p>",
        "labels": labels if labels is not None else [{"title": "zcode"}],
        "assignees": assignees if assignees is not None else [],
        "done": done,
    }


def test_manifest_accepts_explicit_zcode_coding_task():
    assert feeder.task_manifest(
        queue_task(), allowed_repos={"dryvist/example"}
    ) == {
        "task_id": 1,
        "kind": "coding",
        "repo": "dryvist/example",
        "prompt": "Add a regression test.",
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"manifest": {"schema": 1, "tool": "zcode", "kind": "triage", "sensitive": False, "repo": "dryvist/example", "prompt": "do"}},
        {"manifest": {"schema": 1, "tool": "zcode", "kind": "coding", "sensitive": True, "repo": "dryvist/example", "prompt": "do"}},
        {"manifest": {"schema": 1, "tool": "claude", "kind": "coding", "sensitive": False, "repo": "dryvist/example", "prompt": "do"}},
        {"manifest": {"schema": 1, "tool": "zcode", "kind": "coding", "sensitive": False, "repo": "dryvist/private-repo", "prompt": "do"}},
        {"manifest": {"schema": 1, "tool": "zcode", "kind": "coding", "sensitive": False, "repo": "dryvist/..", "prompt": "do"}},
        {"labels": [{"title": "zcode"}, {"title": "sensitive"}]},
        {"labels": [{"title": "coding"}]},
        {"task_id": True},
        {"description": "not a manifest"},
        {"done": True},
        {"assignees": [{"id": 9}]},
    ],
)
def test_manifest_rejects_non_coding_sensitive_or_unapproved_tasks(updates):
    task = queue_task(**updates)
    assert feeder.task_manifest(task, allowed_repos={"dryvist/example"}) is None


def test_selection_is_oldest_eligible_only():
    older = queue_task(task_id=2)
    older["created"] = "2026-10-02T00:00:00Z"
    already_claimed = queue_task(task_id=1, assignees=[{"id": 7}])
    assert feeder.choose_task(
        [queue_task(task_id=3), already_claimed, older],
        allowed_repos={"dryvist/example"},
    )["task_id"] == 2


class FakeAPI:
    def __init__(self, tasks=None, claim=True):
        self.tasks = tasks or []
        self.claimed = []
        self.comments = []
        self.claim_result = claim

    def current_user_id(self):
        return 7

    def list_tasks(self):
        return self.tasks

    def claim(self, task_id, user_id):
        self.claimed.append((task_id, user_id))
        return self.claim_result

    def post_result_once(self, task_id, comment):
        if comment not in self.comments:
            self.comments.append(comment)

    def close_task(self, task_id):
        self.closed = task_id


def config(tmp_path):
    return {
        "allowed_repositories": ["dryvist/example"],
        "label": "zcode",
        "dispatch_state_dir": str(tmp_path / "dispatch"),
    }


def test_persists_claim_before_start_and_saves_valid_job(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    api = FakeAPI([queue_task()])
    calls = []

    def dispatch(_command, *args):
        calls.append(args)
        state = json.loads(state_path.read_text())
        assert state["tasks"]["1"]["state"] == "dispatching"
        return {
            "job": "j-0123456789abcdef",
            "tool": "zcode",
            "repo": "dryvist/example",
            "state": "running",
            "duration": 0,
            "pr": "",
        }

    monkeypatch.setattr(feeder, "_dispatcher", dispatch)
    assert feeder.process_once(config(tmp_path), api, state_path, ["agent-dispatch"]) == "started"
    assert calls == [("start", "zcode", "dryvist/example", "Add a regression test.")]
    assert api.claimed == [(1, 7)]
    assert json.loads(state_path.read_text())["tasks"]["1"]["job_id"] == "j-0123456789abcdef"


def test_unknown_launch_is_marked_for_reconciliation_and_never_restarted(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    feeder.save_state(state_path, {"tasks": {"1": {"state": "dispatching", "repo": "dryvist/example"}}})
    api = FakeAPI([queue_task()])
    monkeypatch.setattr(feeder, "_dispatcher", lambda *_args: pytest.fail("must not relaunch"))

    with pytest.raises(RuntimeError, match="manual reconciliation"):
        feeder.process_once(config(tmp_path), api, state_path, ["agent-dispatch"])
    assert json.loads(state_path.read_text())["tasks"]["1"]["state"] == "reconciliation-needed"
    with pytest.raises(RuntimeError, match="manual reconciliation"):
        feeder.process_once(config(tmp_path), api, state_path, ["agent-dispatch"])


def test_terminal_result_is_six_lines_and_posted_once(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    feeder.save_state(
        state_path,
        {"tasks": {"1": {"state": "running", "repo": "dryvist/example", "job_id": "j-0123456789abcdef"}}},
    )
    api = FakeAPI()
    monkeypatch.setattr(
        feeder,
        "_dispatcher",
        lambda *_args: {
            "job": "j-0123456789abcdef",
            "tool": "zcode",
            "repo": "dryvist/example",
            "state": "succeeded",
            "duration": 42,
            "pr": "https://github.com/dryvist/example/pull/3",
        },
    )
    assert feeder.process_once(config(tmp_path), api, state_path, ["agent-dispatch"]) == "idle"
    assert len(api.comments) == 1
    assert api.comments[0].splitlines() == [
        "job: j-0123456789abcdef",
        "tool: zcode",
        "repo: dryvist/example",
        "state: succeeded",
        "pr: https://github.com/dryvist/example/pull/3",
        "duration: 42s",
    ]
    assert api.closed == 1
    assert json.loads(state_path.read_text())["tasks"]["1"]["state"] == "complete"


def test_lost_comment_response_is_reconciled_without_duplicate():
    class LostResponse(feeder.Vikunja):
        def __init__(self):
            self.comment = None
            self.puts = 0

        def request(self, method, path, body=None):
            if method == "GET" and path.endswith("/comments"):
                return ([{"comment": self.comment}] if self.comment else []), {}
            if method == "PUT" and path.endswith("/comments"):
                self.puts += 1
                self.comment = body["comment"]
                raise RuntimeError("lost response")
            raise AssertionError((method, path))

    api = LostResponse()
    api.post_result_once(9, "job: j-0123456789abcdef")
    assert api.puts == 1
