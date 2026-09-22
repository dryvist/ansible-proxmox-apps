from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles" / "cribl_stream" / "tasks" / "main.yml"


def _task_named(name: str):
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    return next(task for task in tasks if task.get("name") == name)


class VictoriaMetricsReconcileContract(unittest.TestCase):
    def test_output_reconcile_when_victoriametrics_destination_is_missing(self):
        facts = _task_named("Extract live Splunk HEC output settings")[
            "ansible.builtin.set_fact"
        ]
        guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

        self.assertIn("cribl_stream_victoriametrics_live", facts)
        self.assertIn("'victoriametrics_rw' not in cribl_stream_outputs_live_ids", guard)

    def test_output_reconcile_when_victoriametrics_destination_url_drifts(self):
        guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

        self.assertIn("cribl_stream_victoriametrics_live.get('url', '')", guard)
        self.assertIn("cribl_stream_victoriametrics_rw_url", guard)

    def test_validation_requires_live_victoriametrics_output(self):
        validation = (
            ROOT / "playbooks" / "validate-pipeline" / "cribl_stream.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("Read live Cribl Stream outputs configuration", validation)
        self.assertIn(
            "Assert VictoriaMetrics remote-write output is configured", validation
        )
        self.assertIn("cribl_stream_victoriametrics_rw_url", validation)


if __name__ == "__main__":
    unittest.main(verbosity=2)
