"""AI/LLM log ingest pipeline tests.

Every ``constants.ai_log_routing`` entry gets a HAProxy TCP frontend that
load-balances to the Cribl Stream pair, where a per-source ``in_ai_<name>``
input stamps index/sourcetype via the ai_stamp connection pipeline and ships
to the per-index Splunk HEC output. This suite drives each entry end-to-end:
sentinel in at ``haproxy:<port>``, event out in ``index=<index>``.

Sender protocol follows the input type: tcpjson sources get one
newline-delimited JSON object; rsyslog-fed sources (syslog-type inputs, see
``AI_SYSLOG_SOURCE_KEYS``) get an RFC3164/5424 syslog line instead.

With no inventory (or an inventory predating ai_log_routing) the parameter
set is empty and the tests skip.
"""

import json
import time
import uuid

import pytest

from .fixtures import AI_SOURCE_IDS, AI_SOURCES, AI_SYSLOG_SOURCE_KEYS
from .helpers import (
    make_syslog_message,
    send_tcp_syslog,
    wait_for_event,
)


def _make_ai_json_line(sentinel, source_key):
    """One newline-delimited JSON event for a tcpjson in_ai_* input.

    No index/sourcetype fields: the ai_stamp evals are conditional
    (``index || ...``), so the pipeline must stamp both — that is exactly
    the contract this test asserts.
    """
    return json.dumps(
        {
            "_raw": f"e2e ai ingest sentinel {sentinel}",
            "datatype": f"e2e-{source_key}",
        }
    ) + "\n"


class TestAiIngestViaHAProxy:
    """Validate every AI/LLM ingest path through HAProxy -> Stream -> Splunk."""

    @pytest.mark.parametrize("source", AI_SOURCES, ids=AI_SOURCE_IDS)
    def test_ai_frontend_routes_to_index(
        self,
        haproxy_host,
        splunk_creds,
        source,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Send a sentinel to the source's HAProxy port and verify routing."""
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-ai-{source.key}-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        if source.key in AI_SYSLOG_SOURCE_KEYS:
            # rsyslog-fed source: the Stream input is syslog-type (TCP only).
            message = make_syslog_message(sentinel, f"e2e-ai-{source.key}")
        else:
            message = _make_ai_json_line(sentinel, source.key)
        send_tcp_syslog(haproxy_host, source.port, message)

        results = wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index=source.expected_index,
            sourcetype=source.expected_sourcetype,
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
        assert results, (
            f"AI ingest {source.label} sentinel {sentinel} did not reach Splunk "
            f"with index={source.expected_index} "
            f"sourcetype={source.expected_sourcetype}"
        )
