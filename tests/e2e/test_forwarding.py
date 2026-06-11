"""NetFlow forwarding test retained outside the syslog issue scope."""

import time

from .helpers import (
    query_splunk,
    send_netflow_v5,
)


class TestNetFlow:
    """Verify NetFlow v5 data is routed to the correct index."""

    def test_netflow_routing(
        self, haproxy_host, constants, splunk_creds
    ):
        """Verify NetFlow v5 UDP traffic routes to index=network.

        Sends a minimal NetFlow v5 packet to the NetFlow port on the
        HAProxy host and verifies data appears in the network index.
        """
        mgmt_url, user, password = splunk_creds
        port = constants["netflow_ports"]["unifi"]

        # Use a unique src_port as a sentinel to correlate the test packet
        sentinel_port = 40000 + (int(time.time()) % 25000)
        send_netflow_v5(haproxy_host, port, src_port=sentinel_port)

        # Filter by the sentinel port to avoid matching pre-existing traffic.
        # Cribl's netflow input emits camelCase field names (srcPort), which
        # Splunk's JSON auto-extraction preserves — src_port never matches.
        search_str = f'index=network srcPort={sentinel_port} | head 5'
        deadline = time.time() + 120

        results = []
        while time.time() < deadline:
            results = query_splunk(
                mgmt_url, user, password, search_str, timeout=30
            )
            if results:
                break
            time.sleep(10)

        assert len(results) > 0, (
            f"NetFlow routing: no events with srcPort={sentinel_port} "
            f"found in index=network after 120s"
        )
