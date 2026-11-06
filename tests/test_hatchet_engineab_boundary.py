"""Credential boundaries exercised through urllib without network access."""

import io
import json
import sys
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener
from urllib.response import addinfourl

import pytest

WORKER = Path(__file__).resolve().parents[1] / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER))
from engineab import digest  # noqa: E402


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("header", ["Authorization", "x-api-key"])
@pytest.mark.parametrize("target", ["https://198.51.100.1/other", "/other"])
def test_authenticated_redirect_is_refused(monkeypatch, status, header, target):
    sent = []

    class Transport(HTTPSHandler):
        def https_open(self, req):
            sent.append(req)
            headers = Message()
            headers["Location"] = target
            response = addinfourl(io.BytesIO(b""), headers, req.full_url, status)
            response.msg = "Redirect"
            return response

    monkeypatch.setattr(digest, "build_opener", lambda handler: build_opener(
        ProxyHandler({}), Transport(), handler
    ))
    with pytest.raises(HTTPError) as error:
        digest.request("https://192.0.2.1/run", {"prompt": "public"}, "test-token", header)
    assert error.value.code == status
    assert len(sent) == 1
    assert sent[0].get_header(header.capitalize()) == (
        "test-token" if header == "x-api-key" else "Bearer test-token"
    )


def test_tokens_only_reach_their_own_endpoints(monkeypatch):
    engines = {name: {"run_url": f"https://192.0.2.1/{name}", "auth_env": name.upper()}
               for name in ("dify", "langflow", "langgraph")}
    for env in ["DIFY", "LANGFLOW", "LANGGRAPH", "SLACK", "GH_TOKEN", "GITHUB_TOKEN"]:
        monkeypatch.setenv(env, f"test-{env}")
    sent = []

    class Transport(HTTPSHandler):
        def https_open(self, req):
            sent.append(req)
            url = req.full_url
            if "/repos/" in url:
                result = {"private": False, "visibility": "public"}
            elif "/search/" in url:
                result = {"total_count": 0, "items": []}
            elif url.endswith("/dify"):
                result = {"data": {"status": "succeeded", "outputs": {"text": "D"}, "total_tokens": 1}}
            elif url.endswith("/langflow"):
                result = {"outputs": [{"outputs": [{"results": {"message": {"text": "F"}}}]}]}
            elif url.endswith("/langgraph"):
                result = {"text": "G", "tokens": 1}
            else:
                result = {"ok": True, "ts": "123"}
            response = addinfourl(io.BytesIO(json.dumps(result).encode()), Message(), url, 200)
            response.msg = "OK"
            return response

    monkeypatch.setattr(digest, "build_opener", lambda handler: build_opener(
        ProxyHandler({}), Transport(), handler
    ))
    result = digest.run({"repos": ["org/repo"], "engines": engines,
                         "slack_channel": "C123", "slack_auth_env": "SLACK"})
    assert all(row["status"] == "succeeded" for row in result["engines"].values())
    assert len(sent) == 7
    for req in sent:
        auth = {key.lower(): value for key, value in req.header_items()
                if key.lower() in {"authorization", "x-api-key"}}
        if "/repos/" in req.full_url or "/search/" in req.full_url:
            assert auth == {}
        elif req.full_url.endswith("/langflow"):
            assert auth == {"x-api-key": "test-LANGFLOW"}
        else:
            env = next((name.upper() for name in engines if req.full_url.endswith(f"/{name}")), "SLACK")
            assert auth == {"authorization": f"Bearer test-{env}"}
        assert b"test-" not in (req.data or b"")
    assert "test-" not in str(result)
