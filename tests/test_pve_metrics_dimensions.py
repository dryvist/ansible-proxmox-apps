"""pve_metrics_normalize must declare vmid/node/storage (and the guest name)
as metric dimensions.

A Metrics-source event carries vmid, node and storage only as plain event
fields. Without a Publish Metrics function the Splunk HEC destination sends
the series with no dimensions, so a search cannot split per-guest series.
The guest name is joined from pve_guest_map.csv, which is deployed (and
referenced by the pipeline) only when the inventory yields at least one guest.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]

PIPELINE = ROOT / "roles/cribl_stream/templates/pipelines/pve_metrics_normalize/conf.yml.j2"
LOOKUP_CSV_TEMPLATE = ROOT / "roles/cribl_stream/templates/lookups/pve_guest_map.csv.j2"

GUESTS = [
    {"vmid": "100", "name": "guest-a"},
    {"vmid": "200", "name": "guest-b"},
]


def _render(template_path: Path, variables: dict) -> str:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(template_path.read_text(encoding="utf-8")))


def _pipeline(variables: dict) -> dict:
    return yaml.safe_load(_render(PIPELINE, variables))


def _fn_ids(pipeline: dict) -> list[str]:
    return [fn["id"] for fn in pipeline["functions"]]


def _publish_conf(pipeline: dict) -> dict:
    return next(fn for fn in pipeline["functions"] if fn["id"] == "publish_metrics")["conf"]


def test_publish_metrics_declares_vmid_node_storage_without_a_guest_list():
    for variables in ({}, {"cribl_stream_pve_guests": []}):
        pipeline = _pipeline(variables)
        assert _fn_ids(pipeline) == ["eval", "publish_metrics"]
        conf = _publish_conf(pipeline)
        assert conf["metricNameField"] == "_metric"
        assert conf["valueField"] == "_value"
        assert conf["dimensions"] == ["node", "vmid", "storage"]


def test_lookup_and_guest_dimension_render_when_guests_are_known():
    pipeline = _pipeline({"cribl_stream_pve_guests": GUESTS})
    assert _fn_ids(pipeline) == ["eval", "lookup", "publish_metrics"]
    lookup = next(fn for fn in pipeline["functions"] if fn["id"] == "lookup")["conf"]
    assert lookup["file"] == "pve_guest_map.csv"
    assert lookup["matchFields"] == [{"eventField": "vmid", "lookupField": "vmid"}]
    assert lookup["outputFields"] == [{"lookupField": "guest", "eventField": "guest"}]
    assert _publish_conf(pipeline)["dimensions"] == ["node", "vmid", "storage", "guest"]


def test_publish_metrics_is_the_last_function_so_every_derived_field_is_in_scope():
    for variables in ({}, {"cribl_stream_pve_guests": GUESTS}):
        assert _fn_ids(_pipeline(variables))[-1] == "publish_metrics"


def test_eval_still_derives_vmid_node_and_storage():
    pipeline = _pipeline({})
    names = [
        add["name"]
        for fn in pipeline["functions"]
        if fn["id"] == "eval"
        for add in fn["conf"]["add"]
    ]
    for dimension in ("vmid", "node", "storage"):
        assert dimension in names


def test_csv_lists_one_row_per_guest():
    rendered = _render(LOOKUP_CSV_TEMPLATE, {"cribl_stream_pve_guests": GUESTS})
    lines = [line for line in rendered.splitlines() if line.strip()]
    assert lines == ["vmid,guest", "100,guest-a", "200,guest-b"]


def test_csv_is_header_only_when_no_guests():
    rendered = _render(LOOKUP_CSV_TEMPLATE, {"cribl_stream_pve_guests": []})
    assert [line for line in rendered.splitlines() if line.strip()] == ["vmid,guest"]


def test_lookup_deploy_task_is_gated_on_a_non_empty_guest_list():
    # Cribl's Lookup function crashes reading a header-only CSV, so the deploy
    # task and the pipeline's Lookup function share one non-empty condition.
    main_yml = (ROOT / "roles/cribl_stream/tasks/main.yml").read_text(encoding="utf-8")
    task = re.search(
        r"- name: Deploy the PVE guest name lookup table.*?(?=\n- name:|\Z)",
        main_yml,
        re.DOTALL,
    )
    assert task, "the PVE guest lookup deploy task must exist"
    assert "when: cribl_stream_pve_guests | default([]) | length > 0" in task.group(0)


def test_guest_list_default_is_built_from_every_inventory_guest_group():
    defaults = (ROOT / "roles/cribl_stream/defaults/main/60-pve-metrics.yml").read_text(
        encoding="utf-8"
    )
    for group in ("containers", "vms", "docker_vms", "splunk_vm"):
        assert f"'{group}'" in defaults
    rendered = _render_defaults_expression(
        {
            "hostvars": {
                "localhost": {
                    "tofu_data": {
                        "containers": {"web": {"vmid": 100, "hostname": "web-host"}},
                        "vms": {},
                        "docker_vms": {"dock": {"vmid": 200}},
                        "splunk_vm": {"splunk": {"vmid": 300, "hostname": "splunk"}},
                    }
                }
            }
        }
    )
    assert rendered == [
        {"vmid": "100", "name": "web-host"},
        {"vmid": "200", "name": "dock"},
        {"vmid": "300", "name": "splunk"},
    ]


def _render_defaults_expression(variables: dict) -> list:
    data = yaml.safe_load(
        (ROOT / "roles/cribl_stream/defaults/main/60-pve-metrics.yml").read_text(
            encoding="utf-8"
        )
    )
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(data["cribl_stream_pve_guests"]))
