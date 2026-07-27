# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Post per-host converge-freshness telemetry to Splunk HEC at end of run.

Why a callback and not a play: a terminal play cannot distinguish a host that
genuinely converged from a host whose failure was swallowed by the site.yml
block/rescue isolation pattern, and it has no access to per-host result counts.
This callback reads Ansible's own end-of-run ``stats`` object, so the success
verdict it publishes is derived from the executor's counters rather than from
anything a play could assert about itself.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
    name: converge_telemetry
    type: notification
    short_description: Ship per-host converge-freshness events to Splunk HEC
    description:
      - Emits one C(ansible:converge) event per host processed by the run,
        carrying the host FQDN, playbook name, repository git SHA and the
        per-host ok/changed/failed/unreachable/rescued counters.
      - Emits one C(ansible:converge:roster) event per inventory host so a
        Splunk alert can detect hosts that exist in inventory but have never
        reported a converge (orphans).
      - Inert unless the converging playbook publishes its configuration with
        C(ansible.builtin.set_stats) under the C(converge_telemetry) key, so
        enabling the plugin globally does not make unrelated playbooks emit.
    requirements:
      - Splunk HEC endpoint reachable from the control node
    options:
      hec_token:
        description: Splunk HEC token. Never read from run stats, so it cannot
          leak into callback output or a stats dump.
        env:
          - name: SPLUNK_HEC_TOKEN
        ini:
          - section: callback_converge_telemetry
            key: hec_token
        type: str
        default: ""
      enabled:
        description: Master off switch for the emitter.
        env:
          - name: ANSIBLE_CONVERGE_TELEMETRY_ENABLED
        ini:
          - section: callback_converge_telemetry
            key: enabled
        type: bool
        default: true
"""

import json
import time

from ansible.module_utils.common.text.converters import to_text
from ansible.module_utils.urls import open_url
from ansible.plugins.callback import CallbackBase

#: Key the converging playbook uses with ``set_stats`` to hand this plugin its
#: tofu-derived configuration (endpoint, index, host FQDN map, git SHA).
STATS_KEY = "converge_telemetry"

SOURCETYPE_CONVERGE = "ansible:converge"
SOURCETYPE_ROSTER = "ansible:converge:roster"
SOURCE = "ansible-proxmox-apps"


def host_status(summary):
    """Return ``success`` only when Ansible itself recorded a clean host run.

    ``rescued`` counts as a failure on purpose: every ``rescue`` block in this
    repository exists solely to record an isolated play failure
    (playbooks/tasks/record_isolated_failure.yml), so a rescued host did not
    converge cleanly even though its ``failures`` counter is zero.
    """
    for counter in ("failures", "unreachable", "rescued"):
        if summary.get(counter, 0):
            return "failed"
    return "success"


def build_events(summaries, config, playbook, now):
    """Build the HEC event list for a finished run.

    :param summaries: mapping of inventory hostname -> Ansible stats summary
    :param config: the ``converge_telemetry`` dict published via ``set_stats``
    :param playbook: basename of the playbook that ran
    :param now: event timestamp (epoch seconds)
    """
    fqdns = config.get("fqdns") or {}
    index = config.get("index") or "ansible"
    git_sha = config.get("git_sha")
    roster = config.get("roster") or []

    def envelope(host, sourcetype, event):
        return {
            "time": now,
            "host": host,
            "source": SOURCE,
            "sourcetype": sourcetype,
            "index": index,
            "event": event,
        }

    events = []
    for hostname in sorted(summaries):
        summary = summaries[hostname]
        fqdn = fqdns.get(hostname, hostname)
        events.append(
            envelope(
                fqdn,
                SOURCETYPE_CONVERGE,
                {
                    "status": host_status(summary),
                    "host": fqdn,
                    "inventory_hostname": hostname,
                    "playbook": playbook,
                    "repo": SOURCE,
                    "git_sha": git_sha,
                    "ok": summary.get("ok", 0),
                    "changed": summary.get("changed", 0),
                    "skipped": summary.get("skipped", 0),
                    "failures": summary.get("failures", 0),
                    "unreachable": summary.get("unreachable", 0),
                    "rescued": summary.get("rescued", 0),
                    "ignored": summary.get("ignored", 0),
                },
            )
        )

    for hostname in sorted(roster):
        fqdn = fqdns.get(hostname, hostname)
        events.append(
            envelope(
                fqdn,
                SOURCETYPE_ROSTER,
                {
                    "host": fqdn,
                    "inventory_hostname": hostname,
                    "playbook": playbook,
                    "repo": SOURCE,
                    "git_sha": git_sha,
                },
            )
        )

    return events


def encode_batch(events):
    """Encode events as the concatenated-JSON body Splunk HEC expects."""
    return "".join(json.dumps(event, sort_keys=True) for event in events)


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "converge_telemetry"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self, *args, **kwargs):
        super(CallbackModule, self).__init__(*args, **kwargs)
        self._playbook_name = "unknown"

    def v2_playbook_on_start(self, playbook):
        self._playbook_name = playbook._file_name.rsplit("/", 1)[-1]

    def v2_playbook_on_stats(self, stats):
        try:
            self._emit(stats)
        except Exception as exc:  # noqa: BLE001 - telemetry must never fail a run
            self._display.warning(
                "converge_telemetry: failed to publish converge freshness: %s" % to_text(exc)
            )

    def _emit(self, stats):
        if not self.get_option("enabled"):
            return

        config = (getattr(stats, "custom", None) or {}).get("_run", {}).get(STATS_KEY)
        if not config:
            # Not a converge run (no playbook published the configuration).
            return

        url = config.get("hec_url")
        if not url:
            self._display.warning("converge_telemetry: no hec_url in run stats; nothing sent")
            return

        token = self.get_option("hec_token")
        if not token:
            self._display.warning(
                "converge_telemetry: SPLUNK_HEC_TOKEN is unset; converge freshness not published"
            )
            return

        summaries = {host: stats.summarize(host) for host in stats.processed}
        events = build_events(summaries, config, self._playbook_name, time.time())
        if not events:
            return

        self._display.vvv("converge_telemetry: posting %d event(s) to %s" % (len(events), url))
        open_url(
            url,
            data=encode_batch(events),
            method="POST",
            headers={
                "Authorization": "Splunk %s" % token,
                "Content-Type": "application/json",
            },
            validate_certs=bool(config.get("verify_tls", False)),
            timeout=int(config.get("timeout", 10)),
        )
        self._display.display(
            "converge_telemetry: published %d converge-freshness event(s)" % len(events)
        )
