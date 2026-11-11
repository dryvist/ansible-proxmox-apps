"""The provider quota probe is one generic program driven by per-executor entries."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
PROBE = ROLE / "files" / "agent-quota-probe.sh"
DEFAULTS = ROLE / "defaults" / "main" / "20-quota-probe.yml"
SERVICE = ROLE / "templates" / "agent-quota-probe.service.j2"
TIMER = ROLE / "templates" / "agent-quota-probe.timer.j2"
TASKS = ROLE / "tasks" / "main.yml"
KEY = "test-key-not-a-secret"
ZCODE_SERIES = 'executor="zcode",window="{window}",source="provider_api"'
FAKE_CURL = """#!/usr/bin/env bash
printf '%s\\n' "$@" >"$FAKE_CURL_ARGV"
cat -- "$FAKE_CURL_BODY"
printf '\\n%s' "$FAKE_CURL_STATUS"
"""


def resolve(value, templar):
    if isinstance(value, str):
        return templar.template(trust_as_template(value)) if "{{" in value else value
    if isinstance(value, dict):
        return {key: resolve(item, templar) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, templar) for item in value]
    return value


def resolved_defaults():
    variables = {"agent_sandbox_zcode_web_env_file": "/etc/agent-sandbox/zcode-service.env"}
    variables.update(yaml.safe_load(DEFAULTS.read_text(encoding="utf-8")))
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    for _ in range(3):
        for name, value in list(variables.items()):
            variables[name] = resolve(value, templar)
    return variables


def render(template, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = {"ansible_managed": "test", **variables}
    return templar.template(trust_as_template(template.read_text(encoding="utf-8")))


def quota_body(units=(3, 6), code=200, drop_reset=False):
    limits = [
        {
            "type": "TOKENS_LIMIT",
            "unit": unit,
            "number": 1,
            "percentage": 40 + index,
            "nextResetTime": 1767225600000 + index * 1000,
            "usage": 10,
            "currentValue": 4,
            "remaining": 96,
        }
        for index, unit in enumerate(units)
    ]
    if drop_reset:
        del limits[0]["nextResetTime"]
    # A non-token entry must be ignored, whatever its unit.
    limits.append({"type": "TIME_LIMIT", "unit": 5, "number": 1, "percentage": 1})
    return {"code": code, "msg": "ok", "success": True, "data": {"limits": limits}}


class QuotaProbeUnits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults = resolved_defaults()
        cls.entry = cls.defaults["agent_sandbox_quota_probe_executors"][0]
        variables = {**cls.defaults, "item": cls.entry}
        cls.service = render(SERVICE, variables)
        cls.timer = render(TIMER, variables)

    def test_entry_defaults_resolve_to_zcode_on(self):
        self.assertIs(self.entry["enabled"], True)
        self.assertEqual(self.entry["executor"], "zcode")
        self.assertEqual(self.entry["output"], "/var/lib/node_exporter/textfile_collector/agent_quota_zcode.prom")

    def test_service_reads_the_key_only_through_the_environment_file(self):
        self.assertIn("EnvironmentFile=-/etc/agent-sandbox/zcode-service.env", self.service)
        self.assertNotIn("ZAI_SUBSCRIPTION_KEY=", self.service)
        for marker in ("Authorization", "Bearer", KEY):
            self.assertNotIn(marker, self.service)

    def test_service_hardening_and_identity(self):
        for line in (
            "Type=oneshot",
            "User=node-exporter",
            "DynamicUser=no",
            "ProtectSystem=strict",
            "ReadWritePaths=/var/lib/node_exporter/textfile_collector",
            "NoNewPrivileges=yes",
            "ExecStart=/usr/local/libexec/agent-sandbox/agent-quota-probe",
        ):
            self.assertIn(line, self.service.splitlines())

    def test_service_passes_the_window_map_as_unit_window_seconds(self):
        self.assertIn("Environment=QUOTA_WINDOWS=3:5h:18000,6:weekly:604800", self.service.splitlines())
        self.assertIn("Environment=QUOTA_KEY_VAR=ZAI_SUBSCRIPTION_KEY", self.service.splitlines())

    def test_timer_runs_every_five_minutes_at_an_odd_offset_with_jitter(self):
        lines = self.timer.splitlines()
        for line in (
            "OnCalendar=*:03/5",
            "RandomizedDelaySec=60",
            "FixedRandomDelay=true",
            "Persistent=false",
            "Unit=agent-quota-probe-zcode.service",
        ):
            self.assertIn(line, lines)

    def test_role_wires_the_quota_probe_tasks(self):
        includes = [task.get("ansible.builtin.include_tasks") for task in yaml.safe_load(TASKS.read_text(encoding="utf-8"))]
        self.assertIn("main/quota_probe.yml", includes)


class QuotaProbeRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        curl = self.bin_dir / "curl"
        curl.write_text(FAKE_CURL, encoding="utf-8")
        curl.chmod(0o755)
        self.textfile = root / "textfile"
        self.textfile.mkdir()
        self.out = self.textfile / "agent_quota_zcode.prom"
        self.argv = root / "argv.txt"
        self.body = root / "body.json"

    def run_probe(self, body, status=200, key=KEY):
        self.body.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        env = {name: value for name, value in os.environ.items() if name != "ZAI_SUBSCRIPTION_KEY"}
        env.update(
            PATH=f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
            FAKE_CURL_ARGV=str(self.argv),
            FAKE_CURL_BODY=str(self.body),
            FAKE_CURL_STATUS=str(status),
            QUOTA_EXECUTOR="zcode",
            QUOTA_URL="https://quota.example.invalid/limit",
            QUOTA_KEY_VAR="ZAI_SUBSCRIPTION_KEY",
            QUOTA_WINDOWS="3:5h:18000,6:weekly:604800",
            QUOTA_OUTPUT=str(self.out),
        )
        if key is not None:
            env["ZAI_SUBSCRIPTION_KEY"] = key
        return subprocess.run(["bash", str(PROBE)], env=env, capture_output=True, text=True, check=False)

    def test_units_3_and_6_render_six_series_and_the_success_timestamp(self):
        result = self.run_probe(quota_body())
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.out.read_text(encoding="utf-8").splitlines()
        last_success = lines.pop()
        self.assertRegex(last_success, r'^agent_quota_probe_last_success_timestamp_seconds\{executor="zcode"\} \d+$')
        self.assertEqual(
            sorted(lines),
            sorted(
                [
                    f"agent_quota_used_percent{{{ZCODE_SERIES.format(window='5h')}}} 40",
                    f"agent_quota_window_seconds{{{ZCODE_SERIES.format(window='5h')}}} 18000",
                    f"agent_quota_reset_timestamp_seconds{{{ZCODE_SERIES.format(window='5h')}}} 1767225600",
                    f"agent_quota_used_percent{{{ZCODE_SERIES.format(window='weekly')}}} 41",
                    f"agent_quota_window_seconds{{{ZCODE_SERIES.format(window='weekly')}}} 604800",
                    f"agent_quota_reset_timestamp_seconds{{{ZCODE_SERIES.format(window='weekly')}}} 1767225601",
                ]
            ),
        )
        self.assertEqual(sorted(p.name for p in self.textfile.iterdir()), ["agent_quota_zcode.prom"])

    def test_journal_gets_one_line_with_status_code_and_key_names(self):
        result = self.run_probe(quota_body())
        self.assertEqual(
            result.stdout.splitlines(),
            ["http_status=200 code=200 limit_keys=currentValue,nextResetTime,number,percentage,remaining,type,unit,usage"],
        )
        self.assertNotIn(KEY, result.stdout + result.stderr)

    def test_key_reaches_curl_through_a_descriptor_not_an_argument(self):
        self.run_probe(quota_body())
        args = self.argv.read_text(encoding="utf-8").splitlines()
        self.assertNotIn(KEY, "\n".join(args))
        self.assertTrue(any(arg.startswith("@/dev/fd/") for arg in args), args)

    def test_failures_remove_the_metrics_file_and_print_one_line(self):
        cases = {
            "non_200_status": (quota_body(), 500, KEY),
            "code_not_200": (quota_body(code=1001), 200, KEY),
            "unknown_unit": (quota_body(units=(3, 9)), 200, KEY),
            "missing_reset_time": (quota_body(drop_reset=True), 200, KEY),
            "no_token_windows": (quota_body(units=()), 200, KEY),
            "key_missing": (quota_body(), 200, None),
        }
        for name, (body, status, key) in cases.items():
            with self.subTest(case=name):
                self.out.write_text("agent_quota_used_percent{stale=\"yes\"} 1\n", encoding="utf-8")
                result = self.run_probe(body, status=status, key=key)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.out.exists())
                self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
                self.assertTrue(result.stdout.startswith("http_status="))
                self.assertNotIn(KEY, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
