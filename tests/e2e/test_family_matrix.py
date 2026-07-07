"""Full ingest-family matrix: one sentinel per family, in at the LB, out in
its Splunk index.

Data-driven from the inventory constants — nothing here hardcodes ports or
indexes:

- ``constants.syslog_port_map``: one syslog sentinel per family to the
  standard frontend port on HAProxy/Nginx (UDP for the macos family — the
  Macs emit RFC3164 datagrams and only Nginx relays UDP; TCP for everything
  else), asserted into the family's index.
- ``constants.ai_log_routing``: one sentinel per AI/LLM source to its
  HAProxy TCP port — newline-delimited JSON for tcpjson inputs, an RFC3164
  line for the rsyslog-fed syslog-type inputs — asserted into the source's
  index.

Families with no live emitter (or whose ingest path has not converged yet)
are skip-marked via the data-driven lists at the top; drop a key from its
list once its path goes live. With no inventory (or one predating a map)
that map's parameter set is empty and its tests skip.
"""

import json
import time
import uuid

import pytest

from .fixtures import SYSLOG_SOURCES, SYSLOG_SOURCE_IDS, inventory_path
from .helpers import (
    make_syslog_message,
    send_tcp_syslog,
    send_udp_syslog,
    wait_for_event,
)


# ---------------------------------------------------------------------------
# Data-driven skip lists — edit HERE as paths converge, not the test bodies.
# ---------------------------------------------------------------------------
# syslog families with no live emitter yet: the pipeline may route them, but
# nothing real sends on the port, so a red run gives no actionable signal.
SYSLOG_FAMILIES_NOT_LIVE = {
    "windows",   # no Windows sender deployed
    "cisco_asa", # no ASA in the lab
}
# AI sources whose ingest path (B4a rollout) has not converged yet.
AI_SOURCES_NOT_LIVE = {
    "openbao_audit",  # gated on the B7a audit-device rollout
}
# UDP-only families (datagram senders relayed by Nginx, not HAProxy TCP).
UDP_FAMILIES = {"macos"}
# rsyslog-fed AI sources: syslog-type Stream inputs — send RFC3164, not JSON.
AI_SYSLOG_SOURCE_KEYS = {"homelab_llm", "openbao_audit"}


def _load_ai_log_routing():
    if not inventory_path().exists():
        return {}
    with open(inventory_path()) as f:
        constants = json.load(f).get("constants", {})
    return constants.get("ai_log_routing", {})


AI_ROUTING = sorted(_load_ai_log_routing().items())
AI_IDS = [key for key, _ in AI_ROUTING]


def _sentinel(prefix):
    return f"e2e-matrix-{prefix}-{uuid.uuid4().hex[:10]}-{int(time.time())}"


class TestSyslogFamilyMatrix:
    """One sentinel per syslog family, standard port in, family index out."""

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_family_sentinel_lands_in_index(
        self,
        haproxy_host,
        splunk_creds,
        source,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        if source.key in SYSLOG_FAMILIES_NOT_LIVE:
            pytest.skip(f"{source.key}: no live emitter yet (see skip list)")

        mgmt_url, user, password = splunk_creds
        sentinel = _sentinel(source.key)
        message = make_syslog_message(sentinel, f"e2e-matrix-{source.key}")

        if source.key in UDP_FAMILIES:
            send_udp_syslog(haproxy_host, source.standard_port, message)
        else:
            send_tcp_syslog(haproxy_host, source.standard_port, message)

        wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index=source.expected_index,
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )


class TestAiFamilyMatrix:
    """One sentinel per ai_log_routing source, TCP port in, index out."""

    @pytest.mark.parametrize(("key", "entry"), AI_ROUTING, ids=AI_IDS)
    def test_ai_sentinel_lands_in_index(
        self,
        haproxy_host,
        splunk_creds,
        key,
        entry,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        if key in AI_SOURCES_NOT_LIVE:
            pytest.skip(f"{key}: ingest path not converged yet (see skip list)")

        mgmt_url, user, password = splunk_creds
        sentinel = _sentinel(key)

        if key in AI_SYSLOG_SOURCE_KEYS:
            message = make_syslog_message(sentinel, f"e2e-matrix-{key}")
        else:
            message = json.dumps(
                {"_raw": f"e2e matrix sentinel {sentinel}", "datatype": f"e2e-{key}"}
            )
        send_tcp_syslog(haproxy_host, entry["port"], message)

        wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index=entry["index"],
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
