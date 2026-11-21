"""Review runner slots register only their own labels; pooled and heavy slots keep self-hosted."""

from pathlib import Path

import yaml

from app_agent_helpers import _render


ROLE = Path(__file__).resolve().parents[1] / "roles" / "github_runner"
ENV = (ROLE / "templates" / "runner.env.j2").read_text(encoding="utf-8")
DEFAULTS = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))


def _env(slot, review_slots, **extra):
    rendered = _render(ENV, {**DEFAULTS, "ansible_managed": "test fixture", "github_runner_org": "example",
                             "github_runner_bao_addr": "https://bao.example.invalid",
                             "github_runner_slot": slot, "github_runner_review_slots": review_slots, **extra})
    return [line for line in rendered.splitlines() if line and not line.startswith("#")]


def test_review_slots_register_review_without_default_labels_or_self_hosted():
    assert {"NO_DEFAULT_LABELS=true", "LABELS=Linux,X64,review"} <= set(_env(1, 2))
    assert {"NO_DEFAULT_LABELS=true", "LABELS=Linux,X64,review,gpu"} <= set(
        _env(2, 2, github_runner_labels_extra="gpu"))


def test_pooled_and_heavy_slots_keep_their_labels_and_default_labels():
    pooled = _env(3, 2)
    assert "LABELS=self-hosted,Linux,X64,proxmox" in pooled
    heavy = _env(1, 0, github_runner_labels_pool="heavy")
    assert "LABELS=self-hosted,Linux,X64,heavy" in heavy
    assert not any(line.startswith("NO_DEFAULT_LABELS") for line in pooled + heavy)
