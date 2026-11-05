from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_TASKS = ROOT / "roles" / "cribl_stream" / "tasks" / "outputs.yml"


def _task_named(name: str, source: Path = OUTPUT_TASKS):
    tasks = yaml.safe_load(source.read_text(encoding="utf-8"))
    return next(task for task in tasks if task.get("name") == name)


class HecPipelineReconcileContract(unittest.TestCase):
    def test_live_llm_output_is_read_for_its_pipeline(self):
        facts = _task_named("Extract live Splunk HEC output settings")[
            "ansible.builtin.set_fact"
        ]

        self.assertIn("cribl_stream_hec_llm_live", facts)
        self.assertIn(".get('outputs', {}).get('splunk_hec_llm', {})", facts["cribl_stream_hec_llm_live"])

    def test_reconcile_flags_base_output_pipeline_drift(self):
        guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

        self.assertIn("cribl_stream_hec_live.get('pipeline', '')", guard)
        self.assertIn("cribl_stream_splunk_hec_post_processing_pipeline", guard)

    def test_reconcile_flags_llm_output_missing_the_index_guard(self):
        guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

        self.assertIn("cribl_stream_hec_llm_live.get('pipeline', '')", guard)
        self.assertIn("'llm_hec_index_guard'", guard)

    def test_llm_pipeline_check_applies_only_when_the_llm_output_is_rendered(self):
        guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

        self.assertIn("(cribl_stream_hec_namespace | default('')) | length > 0", guard)
        self.assertIn("'llm' in cribl_stream_per_index_indexes", guard)


if __name__ == "__main__":
    unittest.main(verbosity=2)
