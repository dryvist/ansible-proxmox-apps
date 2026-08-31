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
      - Inert in check mode. A dry run changes nothing on the targets, so
        publishing a C(success) event for it would refresh the freshness clock
        of a host that was never actually converged — exactly the staleness the
        downstream alert exists to detect.
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
import atexit
import time

from ansible import context
from ansible.module_utils.common.text.converters import to_text
from ansible.module_utils.urls import open_url
from ansible.plugins.callback import CallbackBase

#: Key the converging playbook uses with ``set_stats`` to hand this plugin its
#: tofu-derived configuration (endpoint, index, host FQDN map, git SHA).
STATS_KEY = "converge_telemetry"

#: Key inside that configuration carrying the playbook's own view of check mode.
CHECK_MODE_KEY = "check_mode"

SOURCETYPE_CONVERGE = "ansible:converge"
SOURCETYPE_ROSTER = "ansible:converge:roster"
SOURCETYPE_TASK = "ansible:converge:task"
SOURCETYPE_INTERRUPTED = "ansible:converge:interrupted"
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


def is_check_mode(config):
    """Return True when this run must not publish converge freshness.

    A check run touches nothing on the targets, so an event from one would
    refresh the freshness clock for a host that never converged — silently
    defeating the >7-day staleness alert this telemetry feeds.

    Two independent signals, either of which is sufficient:

    * ``config[CHECK_MODE_KEY]`` — the converging playbook's own
      ``ansible_check_mode``, handed over with the rest of the configuration
      via ``set_stats``. Authoritative and available however the run was
      launched.
    * ``context.CLIARGS['check']`` — the ``--check`` flag as parsed by the CLI.
      This is how ansible-core's own ``default`` callback reads check mode.
      Empty for API-driven runs (``ansible-runner`` and friends), which is why
      the ``set_stats`` signal above exists as well.
    """
    if (config or {}).get(CHECK_MODE_KEY):
        return True
    return bool((context.CLIARGS or {}).get("check"))


def _desired_state_fields(config):
    """Fields describing whether the converged-against inventory was current.

    Returns an empty dict when the verdict is absent, so a run that could not
    check publishes no claim at all. A default of ``True`` here would make the
    downstream alert silently green for every converge that never ran the check
    — the same class of silent hold the alert exists to catch.
    """
    verdict = (config or {}).get("desired_state_current")
    if verdict is None:
        return {}
    return {
        "desired_state_current": bool(verdict),
        "desired_state_published": (config or {}).get("desired_state_published") or "",
        "desired_state_live": (config or {}).get("desired_state_live") or "",
    }


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

    # Whether the inventory this run converged against was itself current with
    # desired state, as reported by the inventory_resolve role. It rides the
    # per-host event rather than a separate sourcetype because the question it
    # answers is per-converge: "what this host was converged against was already
    # out of date". Absent when the role could not check (no store credentials,
    # or an artifact older than the fingerprint contract) — and absent must stay
    # absent rather than defaulting to True, or a converge that never checked
    # would report the artifact current.
    desired_state = _desired_state_fields(config)

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
                    **desired_state,
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


def build_task_events(tasks, config, playbook, now):
    """Build one event per executed task, carrying its wall-clock duration.

    Per-task timing was previously visible ONLY in `profile_tasks` stdout, which
    is written to a local run log and shipped nowhere. So "which task is slow"
    could not be answered from the observability platform at all -- it required
    reading a log file off the machine that happened to run the converge. That
    is how a single task burning 776 seconds (12.9 min of a 40-min converge)
    stayed unnoticed: nothing was measuring it where anyone would look.

    One event per task rather than per task-and-host: this mirrors what
    `profile_tasks` reports (wall clock for the whole task across every host it
    fanned out to), which is the number that actually explains converge
    duration. Per-host granularity would multiply event volume by the roster
    size to answer a question nobody was asking.
    """
    index = config.get("index") or "ansible"
    git_sha = config.get("git_sha")

    events = []
    for task in tasks:
        events.append(
            {
                "time": task["ended"],
                "host": config.get("controller") or "controller",
                "source": SOURCE,
                "sourcetype": SOURCETYPE_TASK,
                "index": index,
                "event": {
                    "playbook": playbook,
                    "repo": SOURCE,
                    "git_sha": git_sha,
                    "task": task["name"],
                    "role": task["role"],
                    "action": task["action"],
                    "duration_seconds": round(task["duration"], 3),
                    "hosts": task["hosts"],
                    "changed": task["changed"],
                    "failed": task["failed"],
                },
            }
        )
    return events


def build_interrupted_event(config, playbook, now):
    """One marker saying the run never finished.

    ``v2_playbook_on_stats`` fires only on a normal end of run, so a converge
    killed by Ctrl-C or a wrapper timeout published nothing at all -- and those
    are the runs worth seeing. Deliberately NOT a per-host freshness event: the
    run converged nothing, so publishing one would refresh the >7-day staleness
    clock for hosts never touched. Where it got to is already in the task
    events published alongside this one.
    """
    return {
        "time": now,
        "host": config.get("controller") or "controller",
        "source": SOURCE,
        "sourcetype": SOURCETYPE_INTERRUPTED,
        "index": config.get("index") or "ansible",
        "event": {
            "playbook": playbook,
            "repo": SOURCE,
            "git_sha": config.get("git_sha"),
            "status": "interrupted",
        },
    }


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
        # Closed-out tasks, oldest first. A task is closed when the NEXT one
        # starts (or at stats), which is how profile_tasks measures too.
        self._tasks = []
        self._open = None
        # Captured from the set_stats task as it runs, NOT at stats time --
        # see _capture_config. None until the converging playbook publishes it.
        self._config = None
        # Set the moment the normal stats path is entered, so the exit hook can
        # never double-publish a run that ended cleanly.
        self._emitted = False
        atexit.register(self._on_interpreter_exit)

    def _close_open_task(self):
        if self._open is None:
            return
        self._open["ended"] = time.time()
        self._open["duration"] = self._open["ended"] - self._open["started"]
        self._tasks.append(self._open)
        self._open = None

    def v2_playbook_on_task_start(self, task, is_conditional=False):
        self._close_open_task()
        self._open = {
            "name": task.get_name(),
            "role": str(task._role) if task._role else None,
            "action": task.action,
            "started": time.time(),
            "ended": None,
            "duration": 0.0,
            "hosts": 0,
            "changed": 0,
            "failed": 0,
        }

    # Ansible routes handler tasks through their own callback; without this a
    # handler's runtime is silently attributed to whatever task preceded it.
    def v2_playbook_on_handler_task_start(self, task):
        self.v2_playbook_on_task_start(task)

    def _count(self, result, key=None):
        if self._open is None:
            return
        self._open["hosts"] += 1
        if key:
            self._open[key] += 1

    def _capture_config(self, result):
        """Take the configuration off the ``set_stats`` task's own result.

        It reaches the ``stats`` object only at end of run, so reading it there
        left an interrupted run with no endpoint to publish to. The same dict
        is in the task result, available ~40 minutes earlier on a converge.
        """
        stats = (result._result or {}).get("ansible_stats") or {}
        config = (stats.get("data") or {}).get(STATS_KEY)
        if config:
            self._config = config

    def v2_runner_on_ok(self, result):
        self._capture_config(result)
        self._count(result, "changed" if result._result.get("changed") else None)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._count(result, None if ignore_errors else "failed")

    def v2_runner_on_unreachable(self, result):
        self._count(result, "failed")

    def v2_runner_on_skipped(self, result):
        self._count(result)

    def v2_playbook_on_start(self, playbook):
        self._playbook_name = playbook._file_name.rsplit("/", 1)[-1]

    def v2_playbook_on_stats(self, stats):
        # Claimed BEFORE emitting, not after: if _emit raises, the run still
        # ended normally and the exit hook must not publish an "interrupted"
        # marker on top of a real end-of-run.
        self._emitted = True
        try:
            self._emit(stats)
        except Exception as exc:  # noqa: BLE001 - telemetry must never fail a run
            self._display.warning(
                "converge_telemetry: failed to publish converge freshness: %s" % to_text(exc)
            )

    def _emit(self, stats):
        if not self.get_option("enabled"):
            return

        config = self._config or (
            (getattr(stats, "custom", None) or {}).get("_run", {}).get(STATS_KEY)
        )
        if not config:
            # Not a converge run (no playbook published the configuration).
            return

        if is_check_mode(config):
            self._display.vvv(
                "converge_telemetry: check mode; converge freshness not published"
            )
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

        self._close_open_task()

        summaries = {host: stats.summarize(host) for host in stats.processed}
        now = time.time()
        events = build_events(summaries, config, self._playbook_name, now)
        events.extend(
            build_task_events(self._tasks, config, self._playbook_name, now)
        )
        if not events:
            return

        self._post(url, token, events, config)
        self._display.display(
            "converge_telemetry: published %d event(s) (%d task timing(s))"
            % (len(events), len(self._tasks))
        )

    def _post(self, url, token, events, config):
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

    def _on_interpreter_exit(self):
        """Publish what we know when the run never reached ``on_stats``.

        Ctrl-C, a wrapper timeout, or any non-zero bail leaves Ansible's stats
        callback unfired. Everything here is best-effort and must never raise:
        the process is already on its way out, and a traceback from an atexit
        hook would be the last thing printed, burying the real cause.

        SIGKILL cannot be caught, so a hard kill still publishes nothing. That
        is a genuine limit, not a case this handles.
        """
        try:
            if self._emitted:
                return
            if not self.get_option("enabled"):
                return
            config = self._config
            if not config:
                # Not a converge run, or it died before the first play's
                # set_stats -- there is no endpoint to publish to.
                return
            if is_check_mode(config):
                return
            url = config.get("hec_url")
            token = self.get_option("hec_token")
            if not url or not token:
                return

            self._close_open_task()
            now = time.time()
            events = build_task_events(self._tasks, config, self._playbook_name, now)
            events.append(
                build_interrupted_event(config, self._playbook_name, now)
            )
            self._post(url, token, events, config)
        except Exception:  # noqa: BLE001 - never raise from an exit hook
            pass
