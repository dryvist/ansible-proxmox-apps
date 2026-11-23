"""Prevent Cribl pipeline templates from using unsupported nullish operators."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_TEMPLATES = ROOT / "roles/cribl_stream/templates/pipelines"
UNSUPPORTED_OPERATORS = re.compile(r"\?\?|\?\.")


def test_pipeline_templates_do_not_use_nullish_operators():
    templates = sorted(PIPELINE_TEMPLATES.rglob("*.j2"))
    assert templates, "expected Cribl pipeline templates to scan"

    offenders = []
    for template in templates:
        for line_number, line in enumerate(template.read_text(encoding="utf-8").splitlines(), start=1):
            if UNSUPPORTED_OPERATORS.search(line):
                relative_path = template.relative_to(ROOT)
                offenders.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert not offenders, "unsupported JavaScript nullish operators in pipeline templates:\n" + "\n".join(offenders)
