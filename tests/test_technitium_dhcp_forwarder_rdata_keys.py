"""The DHCP guest forwarder check reads FWD rData with the API's camelCase keys."""
from pathlib import Path

TASKS = Path(__file__).resolve().parents[1] / "roles/technitium_dns/tasks/main/dhcp_guest_forwarders.yml"


def test_fwd_rdata_keys_match_the_technitium_api():
    text = TASKS.read_text(encoding="utf-8")
    for key in ("forwarder", "protocol", "dnssecValidation", "proxyType"):
        assert f"'rData.{key}'" in text
    for key in ("Forwarder", "Protocol", "DnssecValidation", "ProxyType"):
        assert f"'rData.{key}'" not in text
