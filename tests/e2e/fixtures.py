"""Shared E2E test fixtures and source matrix."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SyslogSource:
    """Expected routing contract for one app-facing syslog source family."""

    key: str
    label: str
    standard_port: int
    expected_index: str
    expected_sourcetype: str


SYSLOG_SOURCES = [
    SyslogSource("unifi", "UniFi", 514, "unifi", "ubiquiti:unifi"),
    SyslogSource("palo_alto", "Palo Alto", 515, "firewall", "pan:firewall"),
    SyslogSource("cisco_asa", "Cisco ASA", 516, "firewall", "cisco:asa"),
    SyslogSource("linux", "Linux", 517, "os", "syslog"),
    SyslogSource("windows", "Windows", 518, "os", "syslog"),
]


SYSLOG_SOURCE_IDS = [source.key for source in SYSLOG_SOURCES]
