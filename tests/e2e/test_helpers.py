"""Unit tests for pure helper functions in helpers.py."""

import errno
import socket

import pytest

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
