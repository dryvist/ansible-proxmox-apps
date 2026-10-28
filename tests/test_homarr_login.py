"""Regression tests for Homarr credentials login session detection."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "roles/homarr/files"
if str(FILES) not in sys.path:
    sys.path.insert(0, str(FILES))

from homarr_trpc import Homarr  # noqa: E402


def _api_with_session(session_status, session_body):
    api = Homarr("http://homarr.example.test")
    responses = iter(
        [
            (200, '{"csrfToken":"csrf"}'),
            (302, ""),
            (session_status, session_body),
        ]
    )
    api._open = lambda _request: next(responses)
    return api


def test_login_accepts_v2_allowlisted_session_user_id():
    api = _api_with_session(200, json.dumps({"user": {"id": "admin-id"}}))

    assert api.login("admin", "password") is True


def test_login_still_accepts_legacy_top_level_user_id():
    api = _api_with_session(200, json.dumps({"userId": "admin-id"}))

    assert api.login("admin", "password") is True


def test_login_rejects_session_without_user_identity():
    api = _api_with_session(200, json.dumps({"user": {"name": "admin"}}))

    assert api.login("admin", "password") is False


def test_login_rejects_non_successful_session_response():
    api = _api_with_session(401, json.dumps({"user": {"id": "admin-id"}}))

    assert api.login("admin", "password") is False
