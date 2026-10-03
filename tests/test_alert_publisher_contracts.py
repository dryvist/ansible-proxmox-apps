"""Offline render and payload contracts; no live service credentials required."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("ALERT_PUBLISHER_EVIDENCE", ROOT / ".omo/evidence/alert-publishers"))


def render(name, **values):
    result = Environment(undefined=StrictUndefined).from_string(
        (ROOT / "roles/grafana_stack/templates/alerting" / name).read_text()
    ).render(**values)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / name.removesuffix(".j2")).write_text(result)
    return yaml.safe_load(result)


class Publishers(unittest.TestCase):
    def test_grafana_rule_retirement_and_grouping(self):
        rules = render("rules.yml.j2", grafana_stack_prometheus_url="http://metrics.invalid",
                       grafana_stack_alert_folder="Alerts", grafana_stack_alert_eval_interval="1m",
                       grafana_stack_alert_secret_age_days=30,
                       grafana_stack_alert_disk_pct=90,
                       grafana_stack_alert_wan_latency_seconds=1)
        self.assertIn({"orgId": 1, "uid": "claude-jsonl-etl-frozen"}, rules["deleteRules"])
        by_uid = {rule["uid"]: rule for group in rules["groups"] for rule in group["rules"]}
        self.assertNotIn("claude-jsonl-etl-frozen", by_uid)
        self.assertEqual(by_uid["infra-targets-down"]["labels"]["severity"], "warning")
        for uid in ("blackbox-probe-down", "infra-targets-down"):
            rule = by_uid[uid]
            self.assertTrue(rule["data"][0]["model"]["expr"].endswith("== bool 0"))
            self.assertEqual(rule["data"][1]["model"]["conditions"][0]["evaluator"],
                             {"type": "gt", "params": [0]})
        policies = render("notification-policies.yml.j2", grafana_stack_alert_contact_point_name="ntfy",
                          grafana_stack_alert_repeat_interval="4h")
        self.assertEqual(policies["policies"][0]["group_by"],
                         ["alertname", "host", "instance", "job", "stream"])

    def test_go_template_produces_bounded_json(self):
        """Execute Go template syntax with fixture equivalents of JSON namespaces."""
        go = os.environ.get("GO") or shutil.which("go")
        self.assertTrue(go, "GO must name an installed Go binary")
        contact = render("contactpoints.yml.j2", grafana_stack_alert_contact_point_name="ntfy",
                         grafana_stack_alert_ntfy_url="https://ntfy.example.test/observability")
        settings = contact["contactPoints"][0]["receivers"][0]["settings"]
        self.assertEqual(settings["httpMethod"], "POST")
        template = settings["customPayload"]["template"]
        (ARTIFACTS / "payload.gotmpl").write_text(template)
        # These two namespace methods emulate Grafana's documented functions;
        # this checks Go execution and JSON bounds, not Grafana API acceptance.
        harness = r'''package main
import ("encoding/json"; "os"; "text/template")
type Collection struct{}
func(Collection) Dict(v ...any) map[string]any { m:=map[string]any{}; for i:=0;i<len(v);i+=2 { m[v[i].(string)]=v[i+1] }; return m }
type Data struct{}
func(Data) ToJSON(v any)(string,error){ b,e:=json.Marshal(v);return string(b),e }
func main(){ b,e:=os.ReadFile(os.Args[1]);if e!=nil{panic(e)}; var input any; if e=json.NewDecoder(os.Stdin).Decode(&input);e!=nil{panic(e)}; t,e:=template.New("payload").Funcs(template.FuncMap{"coll":func()Collection{return Collection{}},"data":func()Data{return Data{}}}).Parse(string(b));if e!=nil{panic(e)};if e=t.Execute(os.Stdout,input);e!=nil{panic(e)} }
'''
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "main.go"
            source.write_text(harness)
            binary = Path(temporary) / "payload"
            env = {**os.environ, "GOCACHE": str(Path(temporary) / "cache"), "GOPROXY": "off"}
            result = subprocess.run([go, "build", "-o", str(binary), str(source)],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for scenario, status, host, summary in [
                ("firing", "firing", "server-a", 'A "quote" and a newline\n'),
                ("resolved", "resolved", "server-a", "Recovered"),
                ("oversized", "firing", "\x01" * 2000, "\x01" * 20000),
                ("unicode", "firing", "🌍" * 2000, "🌍" * 20000),
                ("unknown-entity", "firing", "", ""),
            ]:
                fixture = {"CommonLabels": {"host": host, "instance": "", "job": "collector", "stream": "etl",
                            "alertname": "\x01" * 2000 if scenario == "oversized" else "rule-a", "severity": "critical"},
                           "CommonAnnotations": {"summary": summary}, "Status": status,
                           "ExternalURL": "https://grafana.example.test", "Alerts": [{}] * 468}
                output = subprocess.run([str(binary), str(ARTIFACTS / "payload.gotmpl")],
                                        input=json.dumps(fixture), capture_output=True, text=True)
                self.assertEqual(output.returncode, 0, output.stderr)
                (ARTIFACTS / f"payload-{scenario}.json").write_text(output.stdout)
                body = json.loads(output.stdout)
                self.assertLess(len(output.stdout.encode()), 4096)
                self.assertEqual(body["status"], status)
                self.assertEqual(body["impact"], "service")
                self.assertEqual(body["alert_count"], 468)
                self.assertNotIn("alerts", body)
                self.assertEqual(set(body), {"source", "rule", "entity", "status", "severity", "impact",
                                             "summary", "details_url", "alert_count"})
                if scenario == "unknown-entity":
                    self.assertEqual(body["entity"], "")

    def test_deadman_transition_reminder_recovery(self):
        source = (ROOT / "roles/service_deadman/templates/service-deadman-validate.sh.j2").read_text()
        functions = source[source.index("mark_ok() {"):source.index("{% for check")]
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "deadman.sh"
            script.write_text("set -eu\nSTATE_DIR=" + temporary + "\nHOST=fixture\nREMIND_MIN=60\n" +
                              "logger() { :; }; gatus_report() { :; }; kuma_report() { :; }; " +
                              "hc_ping() { :; }; offsite_hc_ping() { :; }\n" +
                              'ntfy_publish() { printf "%s|%s|%s|%s\\n" "$1" "$2" "$3" "$4"; }\n' +
                              functions + "\nmark_fail fixture\nmark_fail fixture\n" +
                              'touch -t 202001010000 "$STATE_DIR/fixture.down"\n' +
                              "mark_fail fixture\nmark_ok fixture\nmark_ok fixture\n" +
                              'test ! -e "$STATE_DIR/fixture.down"\n')
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True)
            (ARTIFACTS / "deadman-transitions.log").write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            messages = result.stdout.splitlines()
            self.assertEqual(len(messages), 3)
            self.assertIn("urgent|rotating_light", messages[0])
            self.assertEqual(messages[0], messages[1])
            self.assertIn("default|white_check_mark,resolved", messages[2])

    def test_prometheus_probe_failure_and_recovery(self):
        promtool = os.environ.get("PROMTOOL") or shutil.which("promtool")
        self.assertTrue(promtool, "PROMTOOL must name an installed promtool binary")
        rules = render("rules.yml.j2", grafana_stack_prometheus_url="http://metrics.invalid",
                       grafana_stack_alert_folder="Alerts", grafana_stack_alert_eval_interval="1m",
                       grafana_stack_alert_secret_age_days=30, grafana_stack_alert_disk_pct=90,
                       grafana_stack_alert_wan_latency_seconds=1)
        by_uid = {rule["uid"]: rule for group in rules["groups"] for rule in group["rules"]}
        checks = []
        for uid in ("blackbox-probe-down", "infra-targets-down"):
            expression = by_uid[uid]["data"][0]["model"]["expr"]
            for at, failed in [("0m", 0), ("1m", 1), ("2m", 0)]:
                checks.append({"expr": expression, "eval_time": at,
                               "exp_samples": [{"labels": '{instance="fixture",job="prometheus"}',
                                                "value": failed}]})
        fixture = {"rule_files": [], "evaluation_interval": "1m", "tests": [{"interval": "1m",
                   "input_series": [{"series": metric + '{instance="fixture",job="prometheus"}',
                                     "values": "1 0 1"} for metric in ("up", "probe_success")],
                   "promql_expr_test": checks}]}
        path = ARTIFACTS / "prometheus-probes.yml"
        path.write_text(yaml.safe_dump(fixture))
        result = subprocess.run([promtool, "test", "rules", str(path)], capture_output=True, text=True)
        (ARTIFACTS / "prometheus-probes.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_cutover_plans(self):
        ansible = os.environ.get("ANSIBLE_PLAYBOOK") or shutil.which("ansible-playbook")
        self.assertTrue(ansible, "ANSIBLE_PLAYBOOK must name an installed ansible-playbook")
        defaults = yaml.safe_load((ROOT / "roles/ntfy_docker/defaults/main.yml").read_text())
        self.assertIs(defaults["ntfy_docker_slack_delivery_verified"], False)
        tasks = yaml.safe_load((ROOT / "roles/ntfy_docker/tasks/slack_fanout.yml").read_text())
        retain = next(t for t in tasks if t["name"].startswith("Keep legacy"))
        retire = next(t for t in tasks if t["name"].startswith("Retire ntfy"))
        self.assertEqual(retain["when"], "not (ntfy_docker_slack_delivery_verified | bool)")
        stop = retire["block"][0]["ansible.builtin.systemd"]
        self.assertEqual((stop["state"], stop["enabled"]), ("stopped", False))
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for scenario, verified, webhooks, expected_exit, expected_stale in [
            ("legacy-preserved", False, {"all": "https://hooks.example.test/all"}, 0, ["retired"]),
            ("missing-webhook", False, {}, 2, None),
            ("verified-retirement", True, {}, 0, ["all-observability", "orphan", "retired"]),
        ]:
            play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
                     "vars": {"ntfy_docker_slack_delivery_verified": verified,
                              "ntfy_docker_topics": ["observability"], "ntfy_docker_slack_routes": [],
                              "ntfy_docker_slack_alerts_key": "all", "ntfy_docker_slack_webhooks": webhooks,
                              "ansible_facts": {"services": {"ntfy-to-slack@orphan.service": {}, "other.service": {}}},
                              "ntfy_docker_to_slack_deployed_envs": {"files": [{"path": "/fixture/all-observability.env"},
                                                                                  {"path": "/fixture/retired.env"}]}},
                     "tasks": [tasks[0], {"ansible.builtin.include_tasks": str(ROOT / "roles/ntfy_docker/tasks/slack_fanout_plan.yml"),
                                          "when": retain["when"]}]}]
            if expected_stale is not None:
                play[0]["tasks"] += [
                    {"ansible.builtin.set_fact": {"planned_retirement": retire["vars"]["ntfy_docker_to_slack_stale"]}},
                    {"ansible.builtin.assert": {"that": [f"planned_retirement | sort == {expected_stale!r}"]}},
                    {"ansible.builtin.copy": {"content": "{{ {'active': ntfy_docker_slack_instances, 'retire': planned_retirement} | to_nice_json }}",
                                              "dest": str(ARTIFACTS / f"{scenario}.json"), "mode": "0600"}}]
            fixture_path = ARTIFACTS / f"{scenario}.yml"
            fixture_path.write_text(yaml.safe_dump(play, sort_keys=False))
            env = {**os.environ, "ANSIBLE_LOCAL_TEMP": str(ARTIFACTS / "ansible-local"),
                   "ANSIBLE_REMOTE_TEMP": str(ARTIFACTS / "ansible-remote")}
            result = subprocess.run([ansible, "-i", "localhost,", str(fixture_path)], env=env,
                                    cwd=ROOT, capture_output=True, text=True)
            (ARTIFACTS / f"{scenario}.log").write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
            if scenario == "missing-webhook":
                self.assertIn("Slack fan-out is not deliverable", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
