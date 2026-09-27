"""unifi_syslog_to_metrics (and ipfix_to_metrics, same shared lookup) must
load every declared function on Cribl Stream 4.20.

Verified root cause (cribl.log, both nodes, every worker start):
  pipe:unifi_syslog_to_metrics "failed to load function" name=eval
    error "Expression cannot have nested scopes"
  pipe:unifi_syslog_to_metrics "failed to load function" name=lookup
    error "Cannot read properties of undefined (reading 'forEach')"
  -> "finished loading and initializing functions" count 5 of 7 declared.

1. The vlan_id/direction Eval expressions were IIFEs
   (`(function(){...})()`). Cribl's Eval Value Expression rejects any nested
   function scope (docs.cribl.io/stream/eval-function). Rewritten as plain
   expressions: this test asserts no `add.value` in either pipeline's eval
   functions contains a `function` keyword or `=>`, then proves the
   rewritten regex/ternary expressions still resolve the documented sample
   lines to the right vlan/action/direction.
2. The Lookup function crashes reading a header-only CSV (empty
   cribl_stream_unifi_networks renders only the `vlan_id,network_name`
   header row). Both pipelines now render the Lookup function (and the
   fixed CSV deploy task, roles/cribl_stream/tasks/main.yml, only ships the
   file) only when cribl_stream_unifi_networks is non-empty; with an empty
   list, vlan falls back to the raw vlan_id and metrics still flow.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]

PIPELINE_DIR = ROOT / "roles/cribl_stream/templates/pipelines"
LOOKUP_CSV_TEMPLATE = ROOT / "roles/cribl_stream/templates/lookups/unifi_vlan_map.csv.j2"

# Real sanitized raw samples from the ticket (interfaces are always brN).
SAMPLE_EGRESS_ACCEPT = (
    "<13>Sep 25 23:18:25 UDW UDW [LOCAL_CUSTOM1-A-1] DESCR=\"x\" "
    "IN= OUT=br8 MAC= SRC=192.0.2.1 DST=192.0.2.2 PROTO=UDP"
)
SAMPLE_INGRESS_ACCEPT = (
    "<13>Sep 25 23:18:07 UDW UDW [LAN_CUSTOM1-A-10000] DESCR=\"x\" "
    "IN=br100 OUT=br5 MAC=DOCUMENTATION-EXAMPLE SRC=192.0.2.10 DST=192.0.2.9 "
    "PROTO=TCP SYN"
)
SAMPLE_INGRESS_DENY = (
    "<13>Sep 25 23:18:11 UDW UDW [LAN_LOCAL-D-1] DESCR=\"x\" "
    "IN=br50 OUT= MAC= SRC=192.0.2.3 DST=192.0.2.4 PROTO=UDP DPT=53"
)


def _render(template_path: Path, cribl_stream_unifi_networks: list) -> str:
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "cribl_stream_unifi_networks": cribl_stream_unifi_networks,
    }
    return templar.template(trust_as_template(template_path.read_text(encoding="utf-8")))


def _eval_add_values(pipeline: dict) -> list[str]:
    values = []
    for fn in pipeline["functions"]:
        if fn["id"] != "eval":
            continue
        for add in fn.get("conf", {}).get("add", []):
            values.append(add["value"])
    return values


# --- 1. No nested function scope in any Eval expression, either pipeline ---


def test_no_pipeline_eval_expression_has_a_nested_function_scope():
    for name in ("unifi_syslog_to_metrics", "ipfix_to_metrics"):
        for networks in ([], [{"key": "vlan_siem", "name": "siem", "vlan": 40}]):
            rendered = _render(PIPELINE_DIR / name / "conf.yml.j2", networks)
            pipeline = yaml.safe_load(rendered)
            for value in _eval_add_values(pipeline):
                assert "function" not in value, (
                    f"{name} (networks={bool(networks)}): nested function "
                    f"scope in eval expression: {value!r}"
                )
                assert "=>" not in value, (
                    f"{name} (networks={bool(networks)}): arrow-function "
                    f"nested scope in eval expression: {value!r}"
                )


# --- 2. Lookup + CSV render only when the network list is non-empty ---


def test_unifi_syslog_to_metrics_skips_lookup_when_networks_undefined():
    # Regression: a caller that renders pipelines.yml directly (e.g. the
    # status_stack AutoKuma bulk-render molecule scenario) never loads the
    # cribl_stream role's own defaults, so cribl_stream_unifi_networks is
    # not merely an empty list here -- it is completely undefined. The
    # template's `| default([])` guard must not require the variable to
    # exist at all.
    templar = Templar(loader=DataLoader())
    templar.available_variables = {}
    rendered = templar.template(
        trust_as_template(
            (PIPELINE_DIR / "unifi_syslog_to_metrics" / "conf.yml.j2").read_text(
                encoding="utf-8"
            )
        )
    )
    fn_ids = [fn["id"] for fn in yaml.safe_load(rendered)["functions"]]
    assert "lookup" not in fn_ids


def test_unifi_syslog_to_metrics_skips_lookup_when_networks_empty():
    rendered = _render(PIPELINE_DIR / "unifi_syslog_to_metrics" / "conf.yml.j2", [])
    pipeline = yaml.safe_load(rendered)
    fn_ids = [fn["id"] for fn in pipeline["functions"]]

    assert "lookup" not in fn_ids
    assert fn_ids == ["drop", "eval", "eval", "aggregation", "publish_metrics", "eval"]
    # vlan still flows, from the raw vlan_id, not a dropped/undefined field.
    vlan_add = next(
        add
        for fn in pipeline["functions"]
        if fn["id"] == "eval"
        for add in fn.get("conf", {}).get("add", [])
        if add["name"] == "vlan"
    )
    assert vlan_add["value"] == "vlan_id"


def test_unifi_syslog_to_metrics_renders_lookup_when_networks_present():
    rendered = _render(
        PIPELINE_DIR / "unifi_syslog_to_metrics" / "conf.yml.j2",
        [{"key": "vlan_siem", "name": "siem", "vlan": 40}],
    )
    pipeline = yaml.safe_load(rendered)
    fn_ids = [fn["id"] for fn in pipeline["functions"]]

    assert fn_ids == [
        "drop",
        "eval",
        "lookup",
        "eval",
        "aggregation",
        "publish_metrics",
        "eval",
    ]
    lookup_fn = next(fn for fn in pipeline["functions"] if fn["id"] == "lookup")
    assert lookup_fn["conf"]["file"] == "unifi_vlan_map.csv"


def test_ipfix_to_metrics_skips_lookup_when_networks_empty():
    rendered = _render(PIPELINE_DIR / "ipfix_to_metrics" / "conf.yml.j2", [])
    pipeline = yaml.safe_load(rendered)
    fn_ids = [fn["id"] for fn in pipeline["functions"]]

    assert "lookup" not in fn_ids
    vlan_add = next(
        add
        for fn in pipeline["functions"]
        if fn["id"] == "eval"
        for add in fn.get("conf", {}).get("add", [])
        if add["name"] == "vlan"
    )
    assert vlan_add["value"] == "vlan_id"


def test_ipfix_to_metrics_renders_lookup_when_networks_present():
    rendered = _render(
        PIPELINE_DIR / "ipfix_to_metrics" / "conf.yml.j2",
        [{"key": "vlan_siem", "name": "siem", "vlan": 40}],
    )
    pipeline = yaml.safe_load(rendered)
    fn_ids = [fn["id"] for fn in pipeline["functions"]]

    assert "lookup" in fn_ids


def test_lookup_table_deploy_task_is_gated_on_a_non_empty_network_list():
    main_yml = (ROOT / "roles/cribl_stream/tasks/main.yml").read_text(encoding="utf-8")
    task = re.search(
        r"- name: Deploy the UniFi VLAN lookup table.*?(?=\n- name:|\Z)",
        main_yml,
        re.DOTALL,
    )
    assert task, "the UniFi VLAN lookup table deploy task must still exist"
    assert "when: cribl_stream_unifi_networks | default([]) | length > 0" in task.group(0)


def test_csv_lookup_is_header_only_when_networks_empty():
    # This is the exact input that crashed Cribl's Lookup function
    # ("Cannot read properties of undefined (reading 'forEach')") before the
    # deploy task above was gated to skip it entirely.
    rendered = _render(LOOKUP_CSV_TEMPLATE, [])
    lines = [line for line in rendered.splitlines() if line.strip()]
    assert lines == ["vlan_id,network_name"]


# --- 3. Rewritten vlan_id/action/direction expressions still resolve the
#        documented sample lines correctly (structural, no JS runtime
#        required in CI; run with node when available for a real check of
#        the exact expressions Cribl evaluates). ---


def _vlan_id(raw: str) -> str:
    m = re.search(r"\bbr(\d+)\b", raw)
    return m.group(1) if m else "wan"


def _action(raw: str) -> str:
    if re.search(r"-A-", raw):
        return "accept"
    if re.search(r"-D-", raw):
        return "deny"
    return "unknown"


def _direction(raw: str) -> str:
    m_in = re.search(r"\bIN=(\S*)", raw)
    if m_in and m_in.group(1):
        return "ingress"
    m_out = re.search(r"\bOUT=(\S*)", raw)
    if m_out and m_out.group(1):
        return "egress"
    return "unknown"


def test_sample_lines_resolve_expected_vlan_action_direction():
    assert _vlan_id(SAMPLE_EGRESS_ACCEPT) == "8"
    assert _action(SAMPLE_EGRESS_ACCEPT) == "accept"
    assert _direction(SAMPLE_EGRESS_ACCEPT) == "egress"  # IN= is empty

    assert _vlan_id(SAMPLE_INGRESS_ACCEPT) == "100"  # first brN token (IN=)
    assert _action(SAMPLE_INGRESS_ACCEPT) == "accept"
    assert _direction(SAMPLE_INGRESS_ACCEPT) == "ingress"  # IN= populated

    assert _vlan_id(SAMPLE_INGRESS_DENY) == "50"
    assert _action(SAMPLE_INGRESS_DENY) == "deny"
    assert _direction(SAMPLE_INGRESS_DENY) == "ingress"


def test_rewritten_eval_expression_text_matches_the_pipeline_render():
    # Guards the Python port above against silently drifting from what's
    # actually deployed: the exact regex substrings the pipeline evaluates
    # must appear verbatim in the rendered conf.yml.
    rendered = _render(
        PIPELINE_DIR / "unifi_syslog_to_metrics" / "conf.yml.j2",
        [{"key": "vlan_siem", "name": "siem", "vlan": 40}],
    )
    assert r"\bbr(\d+)\b" in rendered
    assert r"IN=(\S*)" in rendered
    assert r"OUT=(\S*)" in rendered
    assert "-A-" in rendered
    assert "-D-" in rendered


def test_node_agrees_with_the_python_port_when_node_is_available():
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        # CI's pytest-suite job (ubuntu-latest, .github/workflows/_data-contract.yml)
        # installs pytest/pyyaml/ansible-core only, no node -- the structural
        # + Python-side checks above are what actually gate merges there.
        import pytest

        pytest.skip("node not available in this environment")

    pipeline = yaml.safe_load(
        _render(
            PIPELINE_DIR / "unifi_syslog_to_metrics" / "conf.yml.j2",
            [{"key": "vlan_siem", "name": "siem", "vlan": 40}],
        )
    )
    eval_fn = pipeline["functions"][1]
    exprs = {add["name"]: add["value"] for add in eval_fn["conf"]["add"]}

    for raw, expected in (
        (SAMPLE_EGRESS_ACCEPT, ("8", "accept", "egress")),
        (SAMPLE_INGRESS_ACCEPT, ("100", "accept", "ingress")),
        (SAMPLE_INGRESS_DENY, ("50", "deny", "ingress")),
    ):
        script = (
            f"const _raw = {raw!r};"
            f"console.log(JSON.stringify(["
            f"{exprs['vlan_id']}, {exprs['action']}, {exprs['direction']}"
            f"]));"
        )
        result = subprocess.run(
            [node, "-e", script], capture_output=True, text=True, check=True
        )
        vlan_id, action, direction = __import__("json").loads(result.stdout)
        assert (vlan_id, action, direction) == expected, raw
