# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Which guests the inventory loader puts in llm_vllm_group, the GPU engine scrape set.

Each case renders the real expression in inventory/load_tofu/lxc_groups.yml
with Ansible's Templar, the engine the loader uses.
"""

import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template


ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = yaml.safe_load(
    (ROOT / "inventory/load_tofu/lxc_groups.yml").read_text(encoding="utf-8")
)["add_lxc_hosts_groups"]


def _in_vllm_group(container, selector=None):
    tofu_data = {"containers": {"gpu": container}}
    if selector is not None:
        tofu_data["llm_gpu_engine"] = selector
    templar = Templar(loader=DataLoader())
    templar.available_variables = {"item": {"key": "gpu", "value": container}, "tofu_data": tofu_data}
    return "llm_vllm_group" in templar.template(trust_as_template(EXPRESSION))


class VllmGroupMembership(unittest.TestCase):
    def test_legacy_tag_joins(self):
        self.assertTrue(_in_vllm_group({"tags": ["llm-vllm"]}))

    def test_selected_vllm_engine_guest_joins(self):
        self.assertTrue(_in_vllm_group({"tags": ["nvidia-gpu"], "llm_gpu_engine_identity": "vllm"}, "vllm"))

    def test_vllm_guest_not_selected_stays_out(self):
        self.assertFalse(_in_vllm_group({"tags": ["nvidia-gpu"], "llm_gpu_engine_identity": "vllm"}, "llama_cpp"))
        self.assertFalse(_in_vllm_group({"tags": ["nvidia-gpu"], "llm_gpu_engine_identity": "vllm"}))

    def test_other_engine_guest_stays_out(self):
        self.assertFalse(_in_vllm_group({"tags": ["nvidia-gpu"], "llm_gpu_engine_identity": "llama_cpp"}, "vllm"))


if __name__ == "__main__":
    unittest.main()
