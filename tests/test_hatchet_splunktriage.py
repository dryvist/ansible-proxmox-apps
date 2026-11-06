"""Private alert triage contracts with fake Splunk, model, Slack, and SDK."""

import json
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

WORKER = Path(__file__).resolve().parents[1] / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER))

from splunktriage import CRON, message, run  # noqa: E402
from splunktriage import client as http  # noqa: E402
from splunktriage.config import validate  # noqa: E402
from splunktriage.tasks import build_tasks  # noqa: E402


def config(tmp_path):
    return {"splunk_url": "https://192.0.2.1:8089", "local_model_url": "http://127.0.0.1:8000/v1",
            "state_path": str(tmp_path / "state.sqlite3")}


def alert(stamp=900, name="occurrence"):
    return {"name": name, "content": {"sid": "sid", "trigger_time": stamp}}


class FakeClient:
    def __init__(self):
        self.sent = []
        self.alerts = [alert()]
        self.fail = False
        self.valid = True
        self.events_seen = []

    def entries(self, path):
        if path.endswith("fired_alerts"):
            return [{"name": "group"}]
        return self.alerts

    def events(self, item):
        self.events_seen.append(item)
        return [{"_raw": f"event {i}"} for i in range(3)]

    def draft(self, name, events):
        return {"what_fired": "trigger", "likely_cause": "hypothesis",
                "top_events": [2, 1, 0], "next_spl": "search index=main"}

    def valid_spl(self, spl):
        return self.valid

    def post(self, text):
        if self.fail:
            raise RuntimeError("delivery failure")
        self.sent.append(text)


def test_grouping_checkpoint_and_dedupe_across_runs(tmp_path):
    fake = FakeClient()
    fake.alerts += [alert(950, "second"), alert(300, "old"), alert(1100, "future")]
    assert run(config(tmp_path), fake, now=1000) == {"posted": 1}
    assert len(fake.events_seen) == 1
    assert fake.events_seen[0]["name"] == "second"
    assert "event 2" in fake.sent[0] and "Next SPL: search" in fake.sent[0]
    assert run(config(tmp_path), fake, now=1000) == {"posted": 0}
    assert run(config(tmp_path), fake, now=1200) == {"posted": 1}


def test_failure_keeps_first_checkpoint_and_retries_later(tmp_path):
    fake = FakeClient()
    fake.fail = True
    with pytest.raises(RuntimeError):
        run(config(tmp_path), fake, now=1000)
    fake.fail = False
    assert run(config(tmp_path), fake, now=2000) == {"posted": 1}
    assert run(config(tmp_path), fake, now=2100) == {"posted": 0}


def test_invalid_spl_is_omitted_and_events_are_actual_quotes(tmp_path):
    fake = FakeClient()
    fake.valid = False
    run(config(tmp_path), fake, now=1000)
    assert "search index=main" not in fake.sent[0]
    assert '> {"_raw": "event 2"}' in fake.sent[0]
    assert "parser validation failed" in fake.sent[0]
    draft = fake.draft("group", [])
    draft["top_events"] = [100]
    with pytest.raises(ValueError):
        message("group", [], draft, fake)


@pytest.mark.parametrize("url", ["https://8.8.8.8/v1", "https://example.invalid/v1",
                                  "http://0.0.0.0/v1", "https://user:pass@127.0.0.1/v1"])
def test_rejects_nonlocal_model_routes(tmp_path, url):
    cfg = config(tmp_path)
    cfg["local_model_url"] = url
    with pytest.raises(ValueError):
        validate(cfg)


def test_rest_bounds_parser_auth_and_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SPLUNK_TOKEN", "fake-splunk")
    monkeypatch.setenv("SPLUNKTRIAGE_MODEL_TOKEN", "fake-model")
    calls = []

    def request(url, data=None, headers=None):
        calls.append((url, data, headers))
        if "/chat/completions" in url:
            return json.dumps({"choices": [{"message": {"content": json.dumps({"next_spl": "x"})}}]})
        path = urlsplit(url).path
        if path.endswith("/sid"):
            return json.dumps({"entry": [{"content": {"eventSearch": "search index=main"}}]})
        if path.endswith("/parser"):
            return json.dumps({"commands": [{"command": "search"}]})
        return json.dumps({"results": [{"_raw": "x"}] * 1001})

    monkeypatch.setattr(http, "request", request)
    client = http.Client(config(tmp_path))
    assert len(client.events(alert())) == 1000
    params = parse_qs(calls[1][1].decode())
    assert params["earliest_time"] == ["600.0"]
    assert params["latest_time"] == ["900.0"]
    assert params["max_count"] == ["1000"]
    assert params["search"] == ["search index=main | head 1000"]
    assert client.valid_spl("search index=main")
    assert parse_qs(urlsplit(calls[-1][0]).query)["parse_only"] == ["true"]
    client.draft("group", [])
    assert calls[-1][0].startswith("http://127.0.0.1:")
    assert json.loads(calls[-1][1])["model"] == "medium"
    assert calls[-1][2]["Authorization"] == "Bearer fake-model"
    with pytest.raises(ValueError):
        client.api("https://8.8.8.8/services/search/parser")


def test_pagination_and_error_response(tmp_path, monkeypatch):
    monkeypatch.setenv("SPLUNK_TOKEN", "fake")
    client = http.Client(config(tmp_path))
    calls = []

    def api(path, params):
        calls.append(params["offset"])
        return {"entry": [{}] * (100 if params["offset"] == 0 else 2)}

    monkeypatch.setattr(client, "api", api)
    assert len(list(client.entries("/services/alerts/fired_alerts"))) == 102
    assert calls == [0, 100]
    monkeypatch.undo()
    monkeypatch.setenv("SPLUNK_TOKEN", "fake")
    monkeypatch.setattr(http, "request", lambda *_: b'{"messages":[{"type":"ERROR"}]}')
    client = http.Client(config(tmp_path))
    assert client.valid_spl("invalid search") is False
    assert client.valid_spl(None) is False


def test_schedule_and_sanitized_errors(monkeypatch):
    import splunktriage.tasks as tasks

    sdk = types.SimpleNamespace(ConcurrencyExpression=lambda **kw: kw,
                               ConcurrencyLimitStrategy=types.SimpleNamespace(GROUP_ROUND_ROBIN="group"),
                               Priority=types.SimpleNamespace(LOW="low"))
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    registered = []

    class Hatchet:
        def task(self, **options):
            def register(handler):
                registered.append((options, handler))
                return handler
            return register

    build_tasks(Hatchet(), {})
    options, handler = registered[0]
    assert options["on_crons"] == [CRON] == ["3,13,23,33,43,53 * * * *"]
    assert options["concurrency"][0]["max_runs"] == 1
    monkeypatch.setattr(tasks, "run", lambda _: (_ for _ in ()).throw(ValueError("private")))
    with pytest.raises(RuntimeError, match="checkpoint retained") as error:
        handler({}, None)
    assert error.value.__suppress_context__
    assert "private" not in str(error.value)


def test_redirects_are_refused():
    assert http.NoRedirect().redirect_request(None, None, 302, "", {}, "https://8.8.8.8") is None
