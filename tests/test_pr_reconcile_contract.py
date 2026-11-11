"""Guard the pr_reconcile role's owner, token, pin, fence, and unit contracts."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/pr_reconcile"
FAKE_FENCE = "example-owner,example-repo*"


def load_defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text())


def unit_section(text, name):
    """Return the key=value pairs of one systemd section, ignoring comments."""
    body = text.split(f"[{name}]", 1)[1].split("\n[", 1)[0]
    pairs = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key] = value
    return pairs


HARDENING = {
    "NoNewPrivileges": "true",
    "ProtectSystem": "strict",
    "PrivateTmp": "true",
    "ProtectHome": "true",
}


def assert_hardened(test, service):
    for key, value in HARDENING.items():
        test.assertEqual(service.get(key), value, key)
    test.assertIn("ReadWritePaths", service)


class PrReconcileContract(unittest.TestCase):
    def test_owner_entries_are_well_formed_and_unique(self):
        owners = load_defaults()["pr_reconcile_owners"]
        self.assertTrue(owners)
        names = [item["owner"] for item in owners]
        self.assertEqual(len(names), len(set(names)))
        for item in owners:
            self.assertRegex(item["owner"], r"^[A-Za-z0-9-]+$")
            self.assertRegex(item["token_path"], r"^[A-Za-z0-9_/-]+$")
            self.assertTrue(item["token_path"].startswith("github-admin/token/pr-reconcile-"))

    def test_fence_is_read_from_the_environment_with_an_empty_default(self):
        text = (ROLE / "defaults/main.yml").read_text()
        self.assertIn(
            "pr_reconcile_fence: \"{{ lookup('env', 'PR_RECONCILE_FENCE') | default('', true) }}\"",
            text,
        )

    def test_fence_is_asserted_non_empty_and_well_formed(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        self.assertIn("pr_reconcile_fence | length > 0", tasks)
        self.assertIn("pr_reconcile_fence is match('^[A-Za-z0-9._*,-]+$')", tasks)

    def test_service_loads_the_fence_from_a_root_only_environment_file(self):
        unit = (ROLE / "templates/pr-reconcile.service.j2").read_text()
        service = unit_section(unit, "Service")
        self.assertEqual(service["EnvironmentFile"], "{{ pr_reconcile_fence_env_file }}")
        self.assertNotIn("PR_RECONCILE_FENCE", unit)
        tasks = (ROLE / "tasks/main.yml").read_text()
        self.assertIn('dest: "{{ pr_reconcile_fence_env_file }}"', tasks)
        self.assertIn('mode: "0400"', tasks.split("Deploy the pr-reconcile fence list", 1)[1].split("- name:", 1)[0])

    def test_fence_environment_file_carries_the_variable_only(self):
        env_file = (ROLE / "templates/pr-reconcile-fence.env.j2").read_text()
        lines = [line for line in env_file.splitlines() if line and not line.startswith("{{")]
        self.assertEqual(lines, ["PR_RECONCILE_FENCE={{ pr_reconcile_fence }}"])
        rendered = env_file.replace("{{ pr_reconcile_fence }}", FAKE_FENCE)
        self.assertRegex(rendered, r"(?m)^PR_RECONCILE_FENCE=[A-Za-z0-9._*,-]+$")

    def test_dry_run_passes_the_fence_to_the_cli(self):
        verify = (ROLE / "tasks/verify.yml").read_text()
        self.assertIn('PR_RECONCILE_FENCE: "{{ pr_reconcile_fence }}"', verify)

    def test_ref_and_commit_are_empty_until_deployment_sets_them(self):
        defaults = load_defaults()
        self.assertEqual(defaults["pr_reconcile_ref"], "")
        self.assertEqual(defaults["pr_reconcile_commit"], "")

    def test_ref_has_renovate_github_tags_comment(self):
        text = (ROLE / "defaults/main.yml").read_text()
        self.assertIn(
            "# renovate: datasource=github-tags depName=JacobPEvans/.github-ai\npr_reconcile_ref:",
            text,
        )

    def test_bun_pin_is_a_version_and_a_sha256(self):
        defaults = load_defaults()
        self.assertRegex(defaults["pr_reconcile_bun_version"], r"^\d+\.\d+\.\d+$")
        self.assertRegex(defaults["pr_reconcile_bun_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("bun-linux-x64.zip", defaults["pr_reconcile_bun_url"])

    def test_approle_pair_reads_the_platform_env_doc(self):
        text = (ROLE / "defaults/main.yml").read_text()
        self.assertIn("OPENBAO_APPROLE_PR_RECONCILE_ROLE_ID", text)
        self.assertIn("OPENBAO_APPROLE_PR_RECONCILE_SECRET_ID", text)
        self.assertNotIn("OPENBAO_APPROLE_GIT_MIRROR", text)

    def test_service_user_is_separate_from_the_mirror_user(self):
        defaults = load_defaults()
        self.assertEqual(defaults["pr_reconcile_user"], "pr-reconcile")
        self.assertEqual(defaults["pr_reconcile_group"], "pr-reconcile")
        self.assertNotEqual(defaults["pr_reconcile_user"], "git-mirror")

    def test_ref_and_commit_are_asserted_before_the_service_runs(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        self.assertIn("pr_reconcile_ref is match('^[A-Za-z0-9._/-]+$')", tasks)
        self.assertIn("pr_reconcile_commit is match('^[0-9a-f]{40}$')", tasks)
        self.assertIn("pr_reconcile_head.stdout == pr_reconcile_commit", tasks)
        self.assertIn("git rev-parse HEAD", tasks)

    def test_agent_unit_runs_as_the_service_user_with_a_private_runtime_dir(self):
        unit = (ROLE / "templates/openbao-pr-reconcile-agent.service.j2").read_text()
        service = unit_section(unit, "Service")
        self.assertEqual(service["User"], "{{ pr_reconcile_user }}")
        self.assertEqual(service["RuntimeDirectory"], "pr-reconcile")
        self.assertEqual(service["RuntimeDirectoryMode"], "0700")
        assert_hardened(self, service)

    def test_token_sink_lives_under_run(self):
        defaults = load_defaults()
        self.assertTrue(defaults["pr_reconcile_bao_token_file"].startswith("/run/"))
        self.assertTrue(defaults["pr_reconcile_runtime_dir"].startswith("/run/"))

    def test_timer_runs_every_five_minutes_off_the_quarter_hours(self):
        timer = unit_section((ROLE / "templates/pr-reconcile.timer.j2").read_text(), "Timer")
        self.assertEqual(timer["OnCalendar"], "*:03/5")
        self.assertEqual(timer["RandomizedDelaySec"], "40")
        self.assertEqual(timer["FixedRandomDelay"], "true")
        self.assertEqual(timer["Persistent"], "true")
        self.assertEqual(timer["Unit"], "pr-reconcile.service")

    def test_tick_service_is_a_hardened_oneshot_as_the_service_user(self):
        unit = (ROLE / "templates/pr-reconcile.service.j2").read_text()
        service = unit_section(unit, "Service")
        self.assertEqual(service["Type"], "oneshot")
        self.assertEqual(service["User"], "{{ pr_reconcile_user }}")
        self.assertEqual(service["UMask"], "0077")
        assert_hardened(self, service)
        self.assertEqual(
            service["ReadWritePaths"],
            "{{ pr_reconcile_runtime_dir }} {{ pr_reconcile_metrics_dir }}",
        )

    def test_tick_service_reads_owners_and_writes_tokens_under_run(self):
        unit = (ROLE / "templates/pr-reconcile.service.j2").read_text()
        self.assertIn(
            "Environment=PR_RECONCILE_TOKEN_DIR={{ pr_reconcile_runtime_dir }}", unit
        )
        self.assertIn(
            "Environment=PR_RECONCILE_OWNERS={{ pr_reconcile_owners | map(attribute='owner') | join(',') }}",
            unit,
        )
        self.assertTrue(load_defaults()["pr_reconcile_runtime_dir"].startswith("/run/"))
        self.assertIn("ExecStartPre={{ pr_reconcile_mint_bin }}", unit)
        self.assertIn("ExecStart={{ pr_reconcile_tick_bin }}", unit)

    def test_mint_clears_the_owner_file_and_keeps_no_partial_token(self):
        script = (ROLE / "templates/pr-reconcile-mint.sh.j2").read_text()
        self.assertIn('rm -f -- "$destination"', script)
        self.assertIn("token mint failed for owner", script)
        self.assertIn("chmod 0400", script)
        self.assertIn("write -field=token", script)
        self.assertIn("no owner token was minted", script)

    def test_cleanup_removes_token_files_but_not_the_agent_sink(self):
        unit = (ROLE / "templates/pr-reconcile.service.j2").read_text()
        self.assertIn("ExecStopPost=/usr/bin/find", unit)
        self.assertIn("-not -name {{ pr_reconcile_bao_token_file | basename }} -delete", unit)

    def test_verify_runs_a_dry_run_for_the_first_owner(self):
        verify = (ROLE / "tasks/verify.yml").read_text()
        self.assertIn('PR_RECONCILE_DRY_RUN: "1"', verify)
        self.assertIn('PR_RECONCILE_OWNERS: "{{ pr_reconcile_owners[0].owner }}"', verify)
        self.assertIn("pr_reconcile_cli_path", verify)
        tasks = (ROLE / "tasks/main.yml").read_text()
        self.assertIn("include_tasks: verify.yml", tasks)

    def test_verify_removes_minted_tokens_even_when_the_dry_run_fails(self):
        verify = (ROLE / "tasks/verify.yml").read_text()
        self.assertIn("  always:", verify)
        always = verify.split("  always:", 1)[1]
        self.assertIn("state: absent", always)
        self.assertIn("{{ pr_reconcile_runtime_dir }}/{{ item.owner }}", always)

    def test_verify_checks_the_mirror_token_file_is_permission_denied(self):
        verify = (ROLE / "tasks/verify.yml").read_text()
        self.assertIn("'Permission denied' in pr_reconcile_mirror_read.stderr", verify)
        self.assertIn("pr_reconcile_mirror_runtime_dir", verify)
        self.assertIn('become_user: "{{ pr_reconcile_user }}"', verify)


if __name__ == "__main__":
    unittest.main()
