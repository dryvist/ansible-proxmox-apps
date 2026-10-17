from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gpu_engine_logs_route_to_ai_ingest_or_timing_sources():
    group = yaml.safe_load(
        (ROOT / "inventory/group_vars/llm_vllm_group.yml").read_text(
            encoding="utf-8"
        )
    )
    routes = group["syslog_forwarder_program_routes"]

    assert {route["program"] for route in routes} == {"llama-server", "sglang", "strata"}
    assert {route["program"]: route["port"] for route in routes} == {
        "llama-server": "{{ tofu_data.constants.syslog_port_map.llm_serving.standard }}",
        "sglang": "{{ llm_gpu_syslog_route_port }}",
        "strata": "{{ llm_gpu_syslog_route_port }}",
    }
    assert "ai_log_routing.homelab_llm.port" in group["llm_gpu_syslog_route_port"]

    vllm_group = yaml.safe_load(
        (ROOT / "inventory/group_vars/llm_gpu_serving_vllm_group.yml").read_text(
            encoding="utf-8"
        )
    )
    assert vllm_group["syslog_forwarder_program_routes"] == [
        {
            "program": "vllm",
            "port": "{{ tofu_data.constants.syslog_port_map.llm_serving.standard }}",
        }
    ]

    syslog_defaults = yaml.safe_load(
        (ROOT / "roles/syslog_forwarder/defaults/main.yml").read_text(encoding="utf-8")
    )
    assert syslog_defaults["syslog_forwarder_target_port"] == (
        "{{ tofu_data.constants.syslog_ports.linux }}"
    )

    routing = yaml.safe_load(
        (ROOT / "roles/cribl_stream/defaults/main/20-splunk-hec-routing.yml").read_text(
            encoding="utf-8"
        )
    )
    assert routing["cribl_stream_ai_input_types"]["homelab_llm"] == "syslog"
