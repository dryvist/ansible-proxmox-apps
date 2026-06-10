"""Pure utility functions for E2E pipeline tests."""

import base64
import json
import socket
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request


def make_syslog_message(sentinel, app_name="ansible-e2e-test"):
    """Build a syslog message with a unique sentinel."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return f"<14>1 {timestamp} ansible-e2e-host {app_name} - - - {sentinel}"


def send_udp_syslog(host, port, message):
    """Send a syslog message via UDP.

    Args:
        host: Target hostname or IP address.
        port: Target UDP port number.
        message: Syslog message string to send.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(message.encode("utf-8"), (host, port))
    finally:
        sock.close()


def send_tcp_syslog(host, port, message, timeout=5):
    """Send a syslog message over TCP."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall((message + "\n").encode("utf-8"))


def _splunk_search_text(search_str):
    """Return a search string accepted by Splunk's search/export endpoint."""
    stripped = search_str.strip()
    if stripped.startswith("|") or stripped.startswith("search "):
        return stripped
    return f"search {stripped}"


def query_splunk(
    mgmt_url,
    user,
    password,
    search_str,
    earliest="-15m",
    timeout=30,
    verify_tls=False,
    raise_errors=False,
):
    """Execute a Splunk search/export query and return result rows.

    Args:
        mgmt_url: Splunk management URL (e.g., https://192.168.0.200:8089).
        user: Splunk username.
        password: Splunk password.
        search_str: SPL search string with or without leading 'search'.
        earliest: Optional earliest_time value for Splunk.
        timeout: HTTP request timeout in seconds.
        verify_tls: Whether to validate the Splunk management certificate.
        raise_errors: Raise urllib errors instead of returning [].

    Returns:
        List of result dicts parsed from JSON-lines export output.
    """
    params = {
        "search": _splunk_search_text(search_str),
        "output_mode": "json",
    }
    if earliest is not None and "earliest=" not in search_str:
        params["earliest_time"] = earliest
    data = urllib.parse.urlencode(params).encode("utf-8")

    credentials = f"{user}:{password}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")

    ssl_ctx = ssl.create_default_context()
    if not verify_tls:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f"{mgmt_url}/services/search/jobs/export",
        data=data,
        method="POST",
        headers={"Authorization": f"Basic {encoded}"},
    )

    results = []
    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
                if "result" in payload:
                    results.append(payload["result"])
    except (urllib.error.URLError, OSError):
        if raise_errors:
            raise
        return []
    return results


def wait_for_event(
    mgmt_url,
    user,
    password,
    sentinel,
    index,
    sourcetype=None,
    timeout=120,
    poll_interval=10,
):
    """Poll Splunk until an event containing the sentinel string appears.

    Args:
        mgmt_url: Splunk management URL.
        user: Splunk username.
        password: Splunk password.
        sentinel: Unique string to search for in events.
        index: Splunk index to search in.
        sourcetype: Optional expected sourcetype.
        timeout: Maximum time in seconds to wait for the event.
        poll_interval: Seconds between search attempts.

    Returns:
        List of matching result dicts from Splunk.

    Raises:
        TimeoutError: If the event is not found within the timeout period.
    """
    sourcetype_clause = f' sourcetype="{sourcetype}"' if sourcetype else ""
    search_str = f'index={index}{sourcetype_clause} "{sentinel}" | head 5'
    deadline = time.time() + timeout

    while time.time() < deadline:
        results = query_splunk(
            mgmt_url,
            user,
            password,
            search_str,
            earliest="-5m",
            timeout=30,
        )
        if results:
            return results
        time.sleep(poll_interval)

    raise TimeoutError(
        f"Event with sentinel '{sentinel}' not found in index={index} "
        f"within {timeout}s"
    )


def send_netflow_v5(host, port, src_port=12345, dst_port=80):
    """Send a minimal NetFlow v5 packet via UDP.

    Constructs a valid NetFlow v5 header with one flow record and sends
    it to the specified host and port. The flow record contains minimal
    data sufficient for Cribl Edge to recognize and route it.

    Args:
        host: Target hostname or IP address.
        port: Target UDP port number.
        src_port: Source port in the flow record (use unique values for test correlation).
        dst_port: Destination port in the flow record (use unique values for test correlation).
    """
    unix_secs = int(time.time())

    # NetFlow v5 header: 24 bytes
    # version(2), count(2), sys_uptime(4), unix_secs(4), unix_nsecs(4),
    # flow_sequence(4), engine_type(1), engine_id(1), sampling_interval(2)
    header = struct.pack(
        "!HHIIIIBBH",
        5,           # version
        1,           # count (1 flow record)
        0,           # sys_uptime
        unix_secs,   # unix_secs
        0,           # unix_nsecs
        1,           # flow_sequence
        0,           # engine_type
        0,           # engine_id
        0,           # sampling_interval
    )

    # NetFlow v5 flow record: 48 bytes
    # src_addr(4), dst_addr(4), nexthop(4), input(2), output(2),
    # packets(4), octets(4), first(4), last(4),
    # src_port(2), dst_port(2), pad1(1), tcp_flags(1), proto(1), tos(1),
    # src_as(2), dst_as(2), src_mask(1), dst_mask(1), pad2(2)
    flow_record = struct.pack(
        "!IIIHHIIIIHHBBBBHHBBH",
        0xC0A800C9,  # src_addr: 192.168.0.201 (RFC 1918 test address)
        0xC0A800CA,  # dst_addr: 192.168.0.202 (RFC 1918 test address)
        0,           # nexthop
        0,           # input interface
        0,           # output interface
        1,           # packets
        64,          # octets
        0,           # first
        0,           # last
        src_port,    # src_port (sentinel for test correlation)
        dst_port,    # dst_port (sentinel for test correlation)
        0,           # pad1
        0,           # tcp_flags
        6,           # proto (TCP)
        0,           # tos
        0,           # src_as
        0,           # dst_as
        24,          # src_mask
        24,          # dst_mask
        0,           # pad2
    )

    packet = header + flow_record

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (host, port))
    finally:
        sock.close()


def post_splunk_hec(hec_url, token, event, index="main", sourcetype="e2e:hec:test"):
    """Post a single event to Splunk HEC and return (status, body)."""
    payload = json.dumps(
        {
            "event": event,
            "index": index,
            "sourcetype": sourcetype,
        }
    ).encode("utf-8")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f"{hec_url}/services/collector/event",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Splunk {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def splunk_hec_health(hec_url):
    """Return (status, body) from the Splunk HEC health endpoint."""
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f"{hec_url}/services/collector/health/1.0",
        method="GET",
    )
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def check_port_tcp(host, port, timeout=2):
    """Check if a TCP port is accepting connections.

    Args:
        host: Target hostname or IP address.
        port: Target TCP port number.
        timeout: Connection timeout in seconds.

    Returns:
        True if the port is open and accepting connections, False otherwise.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def check_port_udp(host, port, timeout=2):
    """Check if a UDP port is reachable (best effort).

    Sends an empty datagram and checks for ICMP unreachable response.
    Note: UDP port checks are inherently unreliable since the protocol
    is connectionless. A True result means no rejection was received,
    not necessarily that a service is listening.

    Args:
        host: Target hostname or IP address.
        port: Target UDP port number.
        timeout: Timeout in seconds to wait for ICMP unreachable.

    Returns:
        True if no rejection was received, False if port is definitely closed.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(b"", (host, port))
        try:
            sock.recvfrom(1024)
        except socket.timeout:
            # No ICMP unreachable received -- port is likely open
            return True
        return True
    except (ConnectionRefusedError, OSError):
        return False
    finally:
        sock.close()
