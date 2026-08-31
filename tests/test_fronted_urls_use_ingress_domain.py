"""A Traefik-fronted URL must be built from the ingress zone, not the apex.

There are two zones. `ingress_domain` (inventory/group_vars/all.yml) is where
every fronted vhost is published: the traefik role composes each router rule as
`<hostname>.<ingress_domain>`, and the technitium_dns role publishes the
matching alias in that same zone. `tofu_data.domain` is the apex, where guest
DHCP leases and direct guest FQDNs live.

Build a fronted name from the apex and nothing errors. The name either does not
resolve at all or resolves to the bare guest, so the request bypasses TLS and
the auth gate. Every consumer keeps working "successfully" while sending
traffic nowhere.

That is not hypothetical. Both endpoints checked here shipped broken:

  * `splunk_hec_base_url` / `splunk_mgmt_base_url` were built from the apex for
    nine days. `splunk-hec.<apex>` was NXDOMAIN the whole time, so Cribl Stream
    egress, the OpenBao voter-health timer and the converge-freshness callback
    were all posting into a hole. The callback catches every exception and
    downgrades it to a warning ("telemetry must never fail a run"), so nothing
    ever went red.

  * The ntfy alert URLs had the same defect, which is worse in kind: an alerting
    path that fails silently removes the signal that would have reported it.

The check is deliberately a fixed list of names rather than "no URL anywhere may
use the apex". The apex is *correct* for a direct-to-guest consumer on a
non-HTTP port -- Postgres on 5432, Mailpit on SMTP -- because the ingress VIP
listens on 443 and serves nothing on those ports. A blanket rule would flag
those, and a check that fails for reasons outside its own subject is a check
someone switches off.

To extend: add the variable to FRONTED_VARS, or the role default file to
FRONTED_ROLE_DEFAULTS. Anything whose URL has no port suffix and is served by
Traefik belongs here.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALL_YML = ROOT / "inventory" / "group_vars" / "all.yml"

# Shared endpoint variables in group_vars/all.yml that name a fronted service.
FRONTED_VARS = (
    "splunk_hec_base_url",
    "splunk_mgmt_base_url",
)

# Role defaults that build a fronted URL inline, as (path, substring-to-find).
FRONTED_ROLE_DEFAULTS = (
    ("roles/openbao/defaults/main/09-snapshots-and-rotation.yml", "https://ntfy."),
    ("roles/service_deadman/defaults/main.yml", "https://ntfy."),
)

APEX = "tofu_data.domain"
INGRESS = "ingress_domain"


def assignment(text, name):
    """The value of a top-level `name:` assignment, folded scalars included.

    Returns "" when the name is absent, never None: a caller that forgets the
    empty case would otherwise get a TypeError from `in` rather than the
    assertion failure it was written to produce.
    """
    line_match = re.search(r"^%s:[ \t]*(.*)$" % re.escape(name), text, re.M)
    if line_match is None:
        return ""
    continuation = re.search(
        r"^%s:\s*(?:>-|>|\|-|\|)?[ \t]*\n?((?:(?!^\S).*\n?)*)" % re.escape(name),
        text,
        re.M,
    )
    folded = continuation.group(1) if continuation else ""
    return (line_match.group(1) + "\n" + folded).strip()


class FrontedUrlsUseIngressDomain(unittest.TestCase):
    def test_all_yml_fronted_vars(self):
        text = ALL_YML.read_text()
        for name in FRONTED_VARS:
            with self.subTest(var=name):
                value = assignment(text, name)
                self.assertNotEqual(
                    "", value, "%s is not defined in %s" % (name, ALL_YML)
                )
                self.assertNotIn(
                    APEX,
                    value,
                    "%s builds a Traefik-fronted URL from the apex zone (%s). "
                    "Fronted names are published only under %s, so this "
                    "resolves to the bare guest or nowhere at all -- silently, "
                    "with no error at any layer. Use {{ %s }}."
                    % (name, APEX, INGRESS, INGRESS),
                )
                self.assertIn(
                    INGRESS,
                    value,
                    "%s must interpolate {{ %s }}; got: %s"
                    % (name, INGRESS, value),
                )

    def test_role_defaults_fronted_urls(self):
        for rel, marker in FRONTED_ROLE_DEFAULTS:
            path = ROOT / rel
            with self.subTest(path=rel):
                self.assertTrue(path.is_file(), "%s is missing" % rel)
                offenders = [
                    line.strip()
                    for line in path.read_text().splitlines()
                    # Skip comments: prose may legitimately name the apex.
                    if marker in line
                    and not line.lstrip().startswith("#")
                    and APEX in line
                ]
                self.assertEqual(
                    [],
                    offenders,
                    "%s builds a fronted URL from the apex zone. Fronted names "
                    "resolve only under %s; from the apex the request goes to "
                    "the bare guest or nowhere, and an alerting path that fails "
                    "this way deletes its own warning. Offending lines: %s"
                    % (rel, INGRESS, offenders),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
