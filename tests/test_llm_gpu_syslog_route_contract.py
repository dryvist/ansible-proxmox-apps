from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_gpu_engine_journald_routes_use_the_existing_ai_ingest_port():
    group = yaml.safe_load(
        (ROOT / "inventory/group_vars/llm_vllm_group.yml").read_text(
            encoding="utf-8"
        )
    )
    routes = group["syslog_forwarder_program_routes"]

    assert {route["program"] for route in routes} == {
        "llama-server",
        "vllm",
        "sglang",
        "strata",
    }
    assert all(route["port"] == "{{ llm_gpu_syslog_route_port }}" for route in routes)
    assert "ai_log_routing.homelab_llm.port" in group["llm_gpu_syslog_route_port"]

    routing = yaml.safe_load(
        (ROOT / "roles/cribl_stream/defaults/main/20-splunk-hec-routing.yml").read_text(
            encoding="utf-8"
        )
    )
    assert routing["cribl_stream_ai_input_types"]["homelab_llm"] == "syslog"
