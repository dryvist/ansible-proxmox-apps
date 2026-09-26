"""The domain->groups scoping map names only real domains and real groups.

playbooks/site/00-load-and-telemetry.yml's "Pre-fetch resource-domain
secrets from OpenBao" play declares openbao_secrets_domain_groups (which
domains this run's hosts need, per group) as hand-maintained data,
independent of the domain list in roles/openbao_secrets/defaults/main/ and
of the group names in that same play's own `hosts:` pattern plus the two
small scope-detection plays immediately above it (media_group; the deadman
watchdog group set). A typo or a renamed/removed domain or group on either
side would make roles/openbao_secrets/tasks/narrow_domains.yml silently
decide a domain is never needed -- exactly the empty-secret-over-a-live-one
failure class this scoping was built not to reintroduce.

The functional behaviour of the narrowing gate itself is proven against the
production task file in tests/openbao_secrets/verify_domain_scoping.yml;
this test only pins the real map's own vocabulary.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PLAYBOOK = ROOT / "playbooks" / "site" / "00-load-and-telemetry.yml"
DOMAIN_GROUPS_FILE = ROOT / "playbooks" / "site" / "vars" / "openbao_secrets_domain_groups.yml"
DOMAINS_FILE = ROOT / "roles" / "openbao_secrets" / "defaults" / "main" / "01-domains.yml"

PREFETCH_PLAY_NAME = "Pre-fetch resource-domain secrets from OpenBao"
MEDIA_SCOPE_GROUP = "media_group"
DEADMAN_SCOPE_GROUPS = {
    "technitium_dns_group",
    "traefik_group",
    "haproxy_group",
    "openbao_group",
    "docker_vms",
}


def _load_plays() -> list[dict]:
    with PLAYBOOK.open() as f:
        return yaml.safe_load(f)


def _prefetch_play() -> dict:
    plays = _load_plays()
    for play in plays:
        if play.get("name") == PREFETCH_PLAY_NAME:
            return play
    raise AssertionError(f"could not find the {PREFETCH_PLAY_NAME!r} play")


def _hosts_pattern_groups(hosts_value: str) -> set[str]:
    return {group for group in re.split(r"[\s:]+", hosts_value) if group}


def _domain_groups() -> dict:
    with DOMAIN_GROUPS_FILE.open() as f:
        return yaml.safe_load(f)["openbao_secrets_domain_groups"]


def _declared_domain_names() -> set[str]:
    with DOMAINS_FILE.open() as f:
        data = yaml.safe_load(f)
    return {domain["name"] for domain in data["openbao_secrets_domains"]}


def test_every_mapped_domain_is_a_real_declared_domain():
    mapped_domains = set(_domain_groups().keys())
    declared_domains = _declared_domain_names()

    unknown = mapped_domains - declared_domains
    assert not unknown, (
        f"openbao_secrets_domain_groups names domain(s) {sorted(unknown)} that "
        f"are not in roles/openbao_secrets/defaults/main/01-domains.yml's "
        f"openbao_secrets_domains ({sorted(declared_domains)}) -- a typo here "
        "makes narrow_domains.yml silently ignore that entry."
    )


def test_every_mapped_group_is_reachable_by_the_scoping_gate():
    play = _prefetch_play()
    in_play_groups = _hosts_pattern_groups(play["hosts"])
    reachable_groups = in_play_groups | {MEDIA_SCOPE_GROUP} | DEADMAN_SCOPE_GROUPS

    all_mapped_groups: set[str] = set()
    for groups in _domain_groups().values():
        all_mapped_groups.update(groups)

    unreachable = all_mapped_groups - reachable_groups
    assert not unreachable, (
        f"openbao_secrets_domain_groups names group(s) {sorted(unreachable)} "
        "that the scoping gate can never see as active: they are neither in "
        "the pre-fetch play's own `hosts:` pattern nor one of the two "
        "out-of-play scope groups (media_group, the deadman watchdog set) "
        "detected by the plays immediately above it -- any domain mapped "
        "ONLY to such a group would never be fetched, on any run."
    )


def test_domains_with_no_traced_consumer_are_left_unmapped_not_guessed():
    # observability and local-cloud have no consumer anywhere in this repo
    # today (see the map's own comment) -- they must be ABSENT from the map
    # (the "always fetch" safe default), never present with a guessed,
    # unverified group list.
    mapped_domains = set(_domain_groups().keys())
    for unconsumed in ("observability", "local-cloud"):
        assert unconsumed not in mapped_domains, (
            f"{unconsumed!r} has no traced consumer in this repo and must stay "
            "out of openbao_secrets_domain_groups so it is always fetched, not "
            "gated on a guessed group list"
        )
