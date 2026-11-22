"""Contract: the workstation connection profile is published only by its dedicated playbook."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_PLAY = "00b-workstation-connections.yml"


def test_the_site_load_does_not_run_the_publish_play() -> None:
    load = (ROOT / "playbooks/site/00-load-and-telemetry.yml").read_text(encoding="utf-8")
    assert PUBLISH_PLAY not in load


def test_the_dedicated_playbook_runs_the_publish_play() -> None:
    dedicated = (ROOT / "playbooks/publish-workstation-connections.yml").read_text(
        encoding="utf-8"
    )
    assert "site/" + PUBLISH_PLAY in dedicated
