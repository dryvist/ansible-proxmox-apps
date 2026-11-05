"""Shared fixtures for the grounded Q&A fill workload tests."""

import json
from datetime import datetime, timezone

GOOD = json.dumps({"pairs": [{"question": f"q{i}", "answer": f"a{i}"} for i in range(5)]})
WHEN = datetime(2026, 11, 5, 18, 30, tzinfo=timezone.utc)
PLATFORM = {
    "kind": "chat",
    "base_url": "https://192.0.2.20/v1",
    "model": "pro6000-direct",
    "max_tokens": 512,
    "auth_env": "GPU_FILL_ROUTER_API_KEY",
    "timeout_s": 300,
}


def chat_reply(content):
    return {"choices": [{"message": {"content": content}}]}
