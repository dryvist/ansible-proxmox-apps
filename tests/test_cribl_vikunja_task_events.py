"""Contract tests for the task-event feed in the Cribl role (source, pipeline, cap)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRIBL = ROOT / "roles/cribl_stream"
DAILY_CAP_BYTES = 20 * 1024 * 1024


def _text(*suffixes: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(CRIBL.rglob("*"))
        if path.is_file() and path.suffix in suffixes
    )


def test_feed_is_declared_and_off_by_default():
    defaults = _text(".yml")
    assert "cribl_stream_vikunja_task_events_enabled: false" in defaults
    assert "vikunja_task_events" in _text(".yml", ".j2")


def test_source_is_the_native_http_source_and_takes_no_literal_shared_value():
    templates = _text(".j2")
    defaults = _text(".yml")
    assert "type: http" in templates
    assert "vikunja_task_events" in templates
    # The accepted header value comes from a variable, never a literal.
    assert "cribl_stream_vikunja_task_events_header_value" in templates
    assert "cribl_stream_vikunja_task_events_header_value: >-" in defaults
    assert "lookup('ansible.builtin.env', 'VIKUNJA_TASK_EVENTS_PASSWORD')" in defaults
    assert "default('vikunja-task-events', true)" in defaults
    assert "CRIBL_VIKUNJA_TASK_EVENTS_HEADER_VALUE" not in defaults


def test_pipeline_keeps_the_actor_and_trims_text():
    templates = _text(".j2")
    for field in ("doer", "event", "task_id", "project_id"):
        assert field in templates
    assert "slice(0, 200)" in templates


def test_daily_cap_is_one_number_and_excess_is_dropped():
    defaults = _text(".yml")
    assert f"cribl_stream_vikunja_task_events_daily_cap_bytes: {DAILY_CAP_BYTES}" in defaults
    templates = _text(".j2")
    assert "(cribl_stream_vikunja_task_events_daily_cap_bytes | int) // 24" in defaults
    assert "id: suppress" in templates
    assert "numAllowed: {{ cribl_stream_vikunja_task_events_hourly_event_cap }}" in templates
    assert "suppressPeriodSec: 3600" in templates
    assert "dropEvents: true" in templates
    assert "onBackpressure: drop" in templates
    assert "throttleRatePerSec" not in templates
    max_event_bytes = 2048
    assert f"cribl_stream_vikunja_task_events_max_event_bytes: {max_event_bytes}" in defaults
    hourly = DAILY_CAP_BYTES // 24 // max_event_bytes
    assert hourly * 24 * max_event_bytes <= DAILY_CAP_BYTES
