"""Offline HTTP and privacy boundary regressions for reindex."""

import io
import sys
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import BaseHandler, build_opener

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       "roles/hatchet_docker/files/gpu_fill_worker"))

from reindex.api import APIs, NoRedirect  # noqa: E402


@pytest.mark.parametrize("service", ["router", "qdrant"])
@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_authenticated_redirect_never_sends_second_request(monkeypatch, service, code):
    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", "fake-router")
    monkeypatch.setenv("GPU_FILL_REINDEX_QDRANT_API_KEY", "fake-db")
    requests = []

    class Transport(BaseHandler):
        handler_order = 100

        def https_open(self, request):
            requests.append(request)
            response = io.BytesIO(b"")
            response.code = code
            response.msg = "redirect"
            headers = Message()
            headers["Location"] = "https://192.0.2.99/stolen"
            response.info = lambda: headers
            return response

    api = APIs({"router_url": "https://192.0.2.1", "qdrant_url": "https://192.0.2.2"})
    api.opener = build_opener(Transport(), NoRedirect())
    with pytest.raises(HTTPError, match="redirects are forbidden"):
        api.call(service, "/request", {"text": "private"}, method="GET")
    assert len(requests) == 1
    assert requests[0].get_header("Authorization" if service == "router" else "Api-key")
