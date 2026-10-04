#!/usr/bin/python3
"""Single-host, fail-closed Vikunja queue consumer for ZCode jobs."""

from __future__ import annotations

import fcntl
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


TERMINAL = {"succeeded", "failed", "cancelled", "timeout"}
ACTIVE = {"starting", "running", "cancelling"}
JOB_ID = re.compile(r"^j-[0-9a-f]{16}$")
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
SENSITIVE_LABELS = {"sensitive", "security", "incident", "private"}


def _description_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    # Vikunja stores task descriptions as HTML. Strip tags after unescaping so
    # a JSON manifest in a paragraph or code block is parsed identically.
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>|</p>|</pre>|</div>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]*>", "", value)
    value = value.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    return value.strip()


def task_manifest(task: dict, *, allowed_repos: set[str], label: str = "zcode") -> dict | None:
    """Return a normalized job only when every explicit queue guard passes."""
    if not isinstance(task, dict) or task.get("done") is not False:
        return None
    if not isinstance(task.get("assignees"), list) or task["assignees"]:
        return None
    task_id = task.get("id")
    if type(task_id) is not int or task_id < 1:
        return None
    labels = task.get("labels")
    if not isinstance(labels, list):
        return None
    label_names = {
        str(item.get("title", item.get("name", ""))).strip().casefold()
        for item in labels
        if isinstance(item, dict)
    }
    if label.casefold() not in label_names or label_names & SENSITIVE_LABELS:
        return None

    try:
        manifest = json.loads(_description_text(task.get("description")))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    if manifest.get("schema") != 1 or manifest.get("tool") != "zcode":
        return None
    if manifest.get("kind") not in {"coding", "review"} or manifest.get("sensitive") is not False:
        return None

    repo = manifest.get("repo")
    prompt = manifest.get("prompt")
    if not isinstance(repo, str) or not REPO.fullmatch(repo):
        return None
    if repo.split("/", 1)[1] in {".", ".."}:
        return None
    if repo.casefold() not in {item.casefold() for item in allowed_repos}:
        return None
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16384:
        return None
    if any(ord(char) < 32 and char not in "\t\n" for char in prompt):
        return None

    return {"task_id": task_id, "kind": manifest["kind"], "repo": repo, "prompt": prompt.strip()}


def choose_task(tasks: list, *, allowed_repos: set[str], label: str = "zcode") -> dict | None:
    """Choose the oldest eligible unassigned task, breaking ties by task id."""
    candidates = []
    for task in tasks:
        if (
            not isinstance(task, dict)
            or not isinstance(task.get("assignees"), list)
            or task["assignees"]
        ):
            continue
        normalized = task_manifest(task, allowed_repos=allowed_repos, label=label)
        if normalized is not None:
            candidates.append((str(task.get("created", "")), normalized["task_id"], normalized))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][2] if candidates else None


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".zcode-feeder-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_state(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict) or not isinstance(state.get("tasks", {}), dict):
            raise ValueError
        return state
    except FileNotFoundError:
        return {"tasks": {}}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("queue state is unreadable; refusing to dispatch") from exc


class Vikunja:
    def __init__(self, base_url: str, token: str, project_id: int):
        parsed = urlsplit(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if not parsed.hostname or (parsed.scheme != "https" and not local_http):
            raise RuntimeError("queue URL must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError("queue URL must not include user information or query data")
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api/v1"):
            self.base_url += "/api/v1"
        self.token = token
        self.project_id = project_id

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else None, response.headers
        except HTTPError as exc:
            raise RuntimeError(f"queue API request failed with HTTP {exc.code}") from None
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise RuntimeError("queue API request failed") from None

    def list_tasks(self) -> list:
        result = []
        page = 1
        while True:
            query = urlencode({"page": page, "per_page": 100})
            tasks, headers = self.request(
                "GET", f"/projects/{self.project_id}/tasks?{query}"
            )
            if not isinstance(tasks, list):
                raise RuntimeError("queue API returned an invalid task list")
            result.extend(tasks)
            pages = int(headers.get("x-pagination-total-pages", page))
            if page >= pages:
                return result
            page += 1

    def current_user_id(self) -> int:
        user, _ = self.request("GET", "/user")
        user_id = user.get("id") if isinstance(user, dict) else None
        if type(user_id) is not int or user_id < 1:
            raise RuntimeError("queue API did not identify the feeder user")
        return user_id

    def claim(self, task_id: int, user_id: int) -> bool:
        task, _ = self.request("GET", f"/tasks/{task_id}")
        assignees = task.get("assignees") if isinstance(task, dict) else None
        if not isinstance(assignees, list):
            raise RuntimeError("queue API returned invalid task assignees")
        ids = {item.get("id") for item in assignees if isinstance(item, dict)}
        if user_id in ids:
            return True
        if ids:
            return False
        try:
            self.request("PUT", f"/tasks/{task_id}/assignees", {"user_id": user_id})
            return True
        except RuntimeError:
            # A concurrent claimant may have won between read and assignment.
            task, _ = self.request("GET", f"/tasks/{task_id}")
            assignees = task.get("assignees") if isinstance(task, dict) else None
            if not isinstance(assignees, list):
                return False
            return user_id in {
                item.get("id") for item in assignees if isinstance(item, dict)
            }

    def result_posted(self, task_id: int, comment: str) -> bool:
        comments, _ = self.request("GET", f"/tasks/{task_id}/comments")
        if not isinstance(comments, list):
            raise RuntimeError("queue API returned invalid task comments")
        return any(_comment_text(item.get("comment")) == comment for item in comments if isinstance(item, dict))

    def post_result_once(self, task_id: int, comment: str) -> None:
        if self.result_posted(task_id, comment):
            return
        rendered = "<p>" + html.escape(comment).replace("\n", "<br>") + "</p>"
        try:
            self.request("PUT", f"/tasks/{task_id}/comments", {"comment": rendered})
        except RuntimeError:
            # A lost response after a committed comment is reconciled by job id.
            if not self.result_posted(task_id, comment):
                raise

    def close_task(self, task_id: int) -> None:
        task, _ = self.request("GET", f"/tasks/{task_id}")
        if not isinstance(task, dict) or task.get("id") != task_id:
            raise RuntimeError("queue API returned an invalid task")
        if task.get("done") is True:
            return
        task["done"] = True
        self.request("PUT", f"/tasks/{task_id}", task)


def _comment_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<br\s*/?>|</p>|</div>", "\n", value, flags=re.I)
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def _dispatcher(command: list[str], *args: str) -> dict:
    result = subprocess.run(
        [*command, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("dispatcher returned invalid JSON") from None
    if result.returncode != 0 or not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError("dispatcher request failed")
    return payload


def _active_dispatch_exists(state_dir: Path) -> bool:
    for job_file in state_dir.glob("j-*/job.json"):
        job_id = job_file.parent.name
        if not JOB_ID.fullmatch(job_id):
            continue
        runs = job_file.parent / "runs"
        for run in runs.iterdir() if runs.exists() else []:
            state_path = run / "state"
            if state_path.is_file() and state_path.read_text(encoding="utf-8").strip() in ACTIVE:
                return True
    return False


def result_comment(job: dict, record: dict) -> str:
    repo = job.get("repo")
    if (
        not isinstance(job.get("job"), str)
        or not JOB_ID.fullmatch(job["job"])
        or job.get("tool") != "zcode"
        or not isinstance(repo, str)
        or repo.casefold() != record["repo"].casefold()
        or job.get("state") not in TERMINAL
        or not isinstance(job.get("duration"), int)
        or job["duration"] < 0
    ):
        raise RuntimeError("dispatcher returned an invalid terminal result")
    pr = job.get("pr") or "none"
    prefix = f"https://github.com/{record['repo']}/pull/"
    if pr != "none" and not (pr.startswith(prefix) and pr[len(prefix) :].isdigit()):
        raise RuntimeError("dispatcher returned an invalid PR URL")
    return (
        f"job: {job['job']}\n"
        f"tool: zcode\n"
        f"repo: {record['repo']}\n"
        f"state: {job['state']}\n"
        f"pr: {pr}\n"
        f"duration: {job['duration']}s"
    )


def process_once(config: dict, api: Vikunja, state_path: Path, dispatcher: list[str]) -> str:
    state = load_state(state_path)
    tasks = state.setdefault("tasks", {})
    user_id = api.current_user_id()

    # Reconcile the one in-flight job before looking for new work.
    for task_id, record in sorted(tasks.items(), key=lambda item: int(item[0])):
        if record.get("state") in {"dispatching", "reconciliation-needed"}:
            if record.get("state") == "dispatching":
                record["state"] = "reconciliation-needed"
                save_state(state_path, state)
            raise RuntimeError("launch has no recorded job id; manual reconciliation required")
        if record.get("state") != "running":
            continue
        job = _dispatcher(dispatcher, "status", record["job_id"])
        if job.get("state") in ACTIVE:
            return "busy"
        comment = result_comment(job, record)
        api.post_result_once(int(task_id), comment)
        api.close_task(int(task_id))
        record["state"] = "complete"
        record["result"] = comment
        save_state(state_path, state)

    if _active_dispatch_exists(Path(config["dispatch_state_dir"])):
        return "busy"

    allowed = set(config["allowed_repositories"])
    candidate = choose_task(api.list_tasks(), allowed_repos=allowed, label=config["label"])
    if candidate is None:
        return "idle"
    task_id = str(candidate["task_id"])
    previous = tasks.get(task_id)
    if previous:
        if previous.get("state") in {"dispatching", "reconciliation-needed"}:
            raise RuntimeError("task has an unresolved launch; manual reconciliation required")
        return "idle"
    if not api.claim(candidate["task_id"], user_id):
        return "claimed elsewhere"

    record = {
        "state": "dispatching",
        "repo": candidate["repo"],
        "kind": candidate["kind"],
        "claimed_at": int(time.time()),
    }
    tasks[task_id] = record
    save_state(state_path, state)
    job = _dispatcher(dispatcher, "start", "zcode", candidate["repo"], candidate["prompt"])
    if (
        not isinstance(job.get("job"), str)
        or not JOB_ID.fullmatch(job["job"])
        or job.get("tool") != "zcode"
        or job.get("repo", "").casefold() != candidate["repo"].casefold()
        or job.get("state") not in ACTIVE | TERMINAL
    ):
        record["state"] = "reconciliation-needed"
        save_state(state_path, state)
        raise RuntimeError("dispatcher launch result was ambiguous; manual reconciliation required")
    record["job_id"] = job["job"]
    record["state"] = "running"
    save_state(state_path, state)
    if job["state"] in TERMINAL:
        api.post_result_once(candidate["task_id"], result_comment(job, record))
        api.close_task(candidate["task_id"])
        record["state"] = "complete"
        save_state(state_path, state)
        return "complete"
    return "started"


def main() -> int:
    config_path = Path(sys.argv[sys.argv.index("--config") + 1])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    api = Vikunja(
        os.environ["VIKUNJA_URL"],
        os.environ["VIKUNJA_API_TOKEN"],
        int(config["project_id"]),
    )
    state_dir = Path(config["state_dir"])
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = state_dir / "feeder.lock"
    with lock_path.open("w") as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = [config["dispatcher"]]
        status = process_once(config, api, state_dir / "state.json", command)
    print(status)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"zcode-feeder: {exc}", file=sys.stderr)
        raise SystemExit(1)
