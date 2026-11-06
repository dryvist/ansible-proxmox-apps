"""Exercise the shared mirror's real expressions without network or S3 writes."""

from pathlib import Path

from ansible.plugins.filter.core import FilterModule
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "playbooks/tasks/addon-mirror"
ENV = NativeEnvironment(undefined=StrictUndefined)
ENV.filters.update({name: FilterModule().filters()[name] for name in ("combine", "from_json")})


def tasks(path):
    return yaml.safe_load(path.read_text())


def fact_expression(name, key):
    task = next(t for t in tasks(SHARED / "sync-and-publish.yml") if t["name"] == name)
    return ENV.from_string(task["ansible.builtin.set_fact"][key])


@pytest.mark.parametrize("rc,current,version,expected", [
    (1, "", "7.3.0", True),
    (0, "7.3.0", "7.3.0", False),
    (0, "7.2.0", "7.3.0", True),
    (0, "7.3.0\n", "7.3.0", False),
])
def test_shared_sync_decisions(rc, current, version, expected):
    template = fact_expression("Compute sync decisions (bucket tag vs resolved latest)", "addon_mirror_plan")
    plan = template.render(addon_mirror_plan=[], item={
        "rc": rc, "stdout": current, "item": {"name": "fixture", "desired_version": version},
    })
    assert plan[0]["needs_sync"] is expected


@pytest.mark.parametrize("extension,prefix", [("zip", "grafana-plugins"), ("crbl", "cribl-packs")])
@pytest.mark.parametrize("downloaded", [True, False])
def test_manifest_uses_downloaded_or_existing_real_checksum(extension, prefix, downloaded):
    template = fact_expression("Build manifest (name → {version, key, sha256})", "addon_mirror_manifest")
    entry = {"name": "fixture", "desired_version": "1.2.3"}
    manifest = template.render(
        item=entry, addon_mirror_manifest={}, addon_mirror_object_storage_prefix=prefix,
        addon_mirror_extension=extension, addon_mirror_to_sync=[entry] if downloaded else [],
        addon_mirror_checksums={"results": [
            {"item": entry, "stat": {"checksum": "a" * 64}},
        ] if downloaded else []},
        addon_mirror_existing_manifest={"stdout": '{"fixture":{"sha256":"' + "b" * 64 + '"}}'},
    )
    assert manifest == {"fixture": {
        "version": "1.2.3", "key": f"{prefix}/fixture.{extension}",
        "sha256": ("a" if downloaded else "b") * 64,
    }}


def test_registry_pins_and_unpinned_infinity():
    registry = yaml.safe_load((ROOT / "roles/grafana_stack/vars/main.yml").read_text())["grafana_stack_plugins"]
    assert {e["name"]: e.get("pin_version") for e in registry} == {
        "yesoreyeram-infinity-datasource": None,
        "volkovlabs-echarts-panel": "7.3.0",
        "marcusolsson-dynamictext-panel": "6.3.1",
        "grafana-polystat-panel": "2.1.16",
    }


@pytest.mark.parametrize("pin,suffix", [(None, ""), ("7.3.0", "/versions/7.3.0")])
def test_controller_resolves_latest_or_pin(pin, suffix):
    resolver = tasks(ROOT / "playbooks/tasks/sync-grafana-plugins/resolve.yml")
    entry = {"name": "fixture"}
    if pin:
        entry["pin_version"] = pin
    query = ENV.from_string(resolver[0]["ansible.builtin.uri"]["url"])
    assert query.render(item=entry, grafana_plugins_api="https://grafana.com/api/plugins") == (
        "https://grafana.com/api/plugins/fixture" + suffix
    )
    asset = ENV.from_string(resolver[-1]["ansible.builtin.set_fact"]["grafana_plugins_desired"])
    desired = asset.render(grafana_plugins_desired=[], grafana_plugins_api="https://grafana.com/api/plugins",
                           item={"item": entry, "json": {"version": "7.3.0"}})
    assert desired[0]["asset_url"].endswith("/versions/7.3.0/download?os=linux&arch=amd64")


def test_both_mirrors_reuse_the_same_storage_tasks():
    for playbook in ("sync-cribl-packs.yml", "sync-grafana-plugins.yml"):
        source = (ROOT / "playbooks" / playbook).read_text()
        for shared in ("preflight", "sync-and-publish", "verify-manifest"):
            assert f"tasks/addon-mirror/{shared}.yml" in source
    sync = tasks(SHARED / "sync-and-publish.yml")
    downloads = next(i for i, t in enumerate(sync) if "ansible.builtin.get_url" in t)
    uploads = next(i for i, t in enumerate(sync) if t["name"] == "Upload synced artifacts to object storage")
    assert downloads < uploads
    assert sync[uploads]["loop"] == "{{ addon_mirror_to_sync }}"
    # A missing object is retryable; an authorization or connectivity failure must abort.
    guard = next(t for t in sync if t["name"] == "Validate query errors are only missing-object cases")
    predicate = ENV.from_string("{{ " + guard["ansible.builtin.assert"]["that"][0] + " }}")
    assert predicate.render(item={"rc": 1, "stderr": "NoSuchKey"})
    assert not predicate.render(item={"rc": 1, "stderr": "AccessDenied"})


def test_datasource_credentials_are_readable_only_by_the_grafana_user():
    provisioning = tasks(ROOT / "roles/grafana_stack/tasks/provisioning.yml")
    datasource = next(t for t in provisioning if t["name"] == "Render grafana datasource provisioning")
    assert datasource["ansible.builtin.template"]["owner"] == "{{ grafana_stack_grafana_uid }}"
    assert datasource["ansible.builtin.template"]["mode"] == "0400"
    assert datasource["no_log"] is True
