"""The voter-health sampler owes the quorum alert a `voters=<n>` token.

The alert that watches consensus lives in another repository and matches on
`voters=(?P<voters>\\d+)`. It discards every line without that token, so a
sampler that stops emitting it does not make the alert noisy — it makes the
alert match nothing, evaluate "no samples", and lose the ability to tell a
degraded cluster from a silent one.

That is not hypothetical: the token was absent for long enough that 15,010
sampler events reached the log platform carrying zero matches, while the alert
sat scheduled and enabled the whole time.

These tests guard the contract and the fail-closed exit. They read the template
as text on purpose — the point is that the emit survives future edits, not that
Jinja renders.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "roles/openbao/templates/openbao-voter-health.sh.j2"
)

# Verbatim from the consuming saved search. Keep these in step.
ALERT_REGEX = re.compile(r"voters=\(\?<voters>\\d\+\)|voters=")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_summary_emits_a_voters_token_the_alert_can_match() -> None:
    """The summary line must carry `voters=` bound to a counted value."""
    body = _template()
    summary = [ln for ln in body.splitlines() if "sweep complete" in ln]
    assert summary, "the sampler no longer logs a sweep summary at all"
    line = summary[0]
    assert "voters=${healthy_count}" in line, (
        "the summary must emit voters=<count>; the consuming alert matches on "
        f"that token and silently drops every line without it. Got: {line}"
    )
    # The rendered form must satisfy the alert's own pattern.
    rendered = line.replace("${healthy_count}", "9")
    assert re.search(r"voters=(\d+)", rendered), rendered


def test_healthy_count_is_actually_incremented() -> None:
    """A token bound to a variable nothing increments always reports zero."""
    body = _template()
    assert "healthy_count=0" in body, "healthy_count is never initialised"
    assert "healthy_count=$((healthy_count + 1))" in body, (
        "healthy_count is emitted but never incremented, so the alert would "
        "read a permanent zero and fire forever"
    )


def test_a_failed_ship_does_not_exit_zero() -> None:
    """A sweep whose ships all failed must not look like a clean sweep."""
    body = _template()
    assert "ship_fail_count=$((ship_fail_count + 1))" in body, (
        "shipping failures are not counted, so they cannot affect the exit code"
    )
    assert re.search(
        r'if \[ "\$\{ship_fail_count\}" -gt 0 \]; then(?:.|\n)*?exit 1', body
    ), (
        "the sampler must exit non-zero when a ship fails; exiting 0 "
        "unconditionally is what made a total shipping failure indistinguishable "
        "from a healthy sweep"
    )


def test_unreachable_voters_are_still_counted_separately() -> None:
    """Voters that did not answer and ships that did not land are different."""
    body = _template()
    assert "fail_count=$((fail_count + 1))" in body
    assert "unreachable=${fail_count}" in body, (
        "the summary must keep reporting unreachable voters distinctly from "
        "ship failures; collapsing them loses which half is broken"
    )
