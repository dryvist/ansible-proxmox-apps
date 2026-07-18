#!/usr/bin/env python3
"""Read-only Nautobot-vs-source drift report (issue #977 gate 3).

Compares what Nautobot currently holds against the source-of-truth facts and
prints a repeatable drift report: modeled-object counts, guest/tag drift (what
Nautobot has that sources lack and vice versa), and the coverage gap for source
domains Nautobot has no model for yet. Read-only — queries the Nautobot REST +
GraphQL API and reads the published inventory artifact; writes nothing.

Environment (same fallbacks as the GraphQL dynamic inventory):
  NAUTOBOT_URL    Nautobot API base URL
  NAUTOBOT_TOKEN  read-only API token
Argument:
  --tofu-inventory PATH   the published inventory artifact (source guests+tags)

Exit code is non-zero only on an API/IO error, never on drift — this is a
report, not a gate.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.request

# Source domains Nautobot core has no model for yet (see the Phase-2 design doc
# §7). Listed so the report states the coverage gap explicitly rather than
# silently omitting it.
UNMODELED_DOMAINS = [
    "firewall groups/rules",
    "DNS records",
    "WLANs",
    "port profiles / port-forwards",
    "static + traffic routes",
    "RADIUS",
    "VPN",
    "WAN",
    "cables",
    "physical device interfaces",
]

GUEST_SECTIONS = ("containers", "vms", "docker_vms", "splunk_vm")


def _get(path: str, url: str, token: str) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + path,
        headers={"Authorization": "Token " + token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
        return json.load(resp)


def _graphql(query: str, url: str, token: str) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/api/graphql/",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": "Token " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45, context=ssl.create_default_context()) as resp:
        return json.load(resp)["data"]


def source_guests(tofu: dict) -> dict[str, set]:
    """Map each source guest hostname -> set of its tags."""
    guests: dict[str, set] = {}
    for section in GUEST_SECTIONS:
        for key, val in (tofu.get(section) or {}).items():
            name = val.get("hostname") or key
            guests[name] = set(val.get("tags") or [])
    return guests


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tofu-inventory", required=True, help="published inventory artifact JSON")
    args = ap.parse_args()
    url = os.environ["NAUTOBOT_URL"]
    token = os.environ["NAUTOBOT_TOKEN"]

    with open(args.tofu_inventory, encoding="utf-8") as handle:
        src = source_guests(json.load(handle))

    data = _graphql("{ virtual_machines { name tags { name } } }", url, token)
    nb = {
        vm["name"]: {t["name"] for t in (vm.get("tags") or [])}
        for vm in data["virtual_machines"]
    }

    counts = {
        model: _get("/api/%s/?limit=1" % model, url, token).get("count")
        for model in (
            "ipam/vlans",
            "ipam/prefixes",
            "ipam/ip-addresses",
            "dcim/devices",
            "virtualization/virtual-machines",
            "extras/tags",
        )
    }

    missing_guests = sorted(set(src) - set(nb))
    extra_guests = sorted(set(nb) - set(src))
    tag_drift = {
        name: sorted(src[name] - nb.get(name, set()))
        for name in src
        if src[name] - nb.get(name, set())
    }
    missing_tag_assignments = sum(len(v) for v in tag_drift.values())

    print("=== Nautobot drift report (read-only) ===")
    print("modeled object counts:")
    for model, count in counts.items():
        print("  %-34s %s" % (model, count))
    print("source guests: %d   nautobot VMs: %d" % (len(src), len(nb)))
    print("guests in sources but MISSING from Nautobot: %d %s"
          % (len(missing_guests), missing_guests[:10]))
    print("VMs in Nautobot NOT in sources: %d %s"
          % (len(extra_guests), extra_guests[:10]))
    print("guests with MISSING tags: %d  (total %d tag assignments to import)"
          % (len(tag_drift), missing_tag_assignments))
    print("coverage gap — source domains with NO Nautobot model yet:")
    for domain in UNMODELED_DOMAINS:
        print("  - %s" % domain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
