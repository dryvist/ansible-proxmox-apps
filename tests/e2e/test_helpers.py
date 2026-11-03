"""Unit tests for pure helper functions in helpers.py."""

import errno
import socket
import urllib.error

import pytest

from . import helpers
from .helpers import check_port_tcp


@pytest.mark.parametrize(
    ("exc", "expected_fault"),
    [
        (TimeoutError(), "timeout after 2s"),
        (ConnectionRefusedError(), "refused"),
        (ConnectionResetError(), "reset"),
        (OSError(errno.EHOSTUNREACH, "No route to host"), "unreachable"),
        (OSError(errno.EACCES, "Permission denied"), "EACCES"),
    ],
)
def test_check_port_tcp_classifies_fault(monkeypatch, exc, expected_fault):
    def raise_exc(self, addr):
        raise exc

    monkeypatch.setattr(socket.socket, "connect", raise_exc)
    result = check_port_tcp("example.invalid", 1234, timeout=2)
    assert not result
    assert result.fault == expected_fault


def test_check_port_tcp_success(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda self, addr: None)
    result = check_port_tcp("example.invalid", 1234)
    assert result
    assert str(result) == "ok"


class _FakeTime:
    """Clock that only moves when the polling loop sleeps."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _wait(sentinel="sentinel-x", timeout=30):
    return helpers.wait_for_event(
        "https://splunk.example.test:8089",
        "user",
        "password",
        sentinel,
        "llm",
        timeout=timeout,
        poll_interval=10,
    )


def test_wait_for_event_retries_query_error_then_returns(monkeypatch):
    calls = []

    def fake_query(*args, **kwargs):
        assert kwargs["raise_errors"] is True
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("timed out")
        return [{"_raw": "sentinel-x"}]

    monkeypatch.setattr(helpers, "query_splunk", fake_query)
    monkeypatch.setattr(helpers, "time", _FakeTime())
    assert _wait(timeout=120) == [{"_raw": "sentinel-x"}]
    assert len(calls) == 2


def test_wait_for_event_timeout_counts_query_errors(monkeypatch):
    def fake_query(*args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(helpers, "query_splunk", fake_query)
    monkeypatch.setattr(helpers, "time", _FakeTime())
    with pytest.raises(TimeoutError) as excinfo:
        _wait(timeout=30)
    message = str(excinfo.value)
    assert "query errors: 3" in message
    assert "last error: OSError: connection reset" in message


def test_wait_for_event_timeout_without_errors_reports_none(monkeypatch):
    monkeypatch.setattr(helpers, "query_splunk", lambda *a, **k: [])
    monkeypatch.setattr(helpers, "time", _FakeTime())
    with pytest.raises(TimeoutError) as excinfo:
        _wait(timeout=30)
    assert "query errors: 0, last error: none" in str(excinfo.value)
