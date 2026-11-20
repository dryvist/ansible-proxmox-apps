"""The agent-write rights are verified through a read-only rails readback.

The verification reads roles, groups, the agent-write user and the API rows on
the host, with no administrator credential, and prints names only.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app_agent_helpers import ROOT, _render, _task, _yaml

READBACK = ROOT / "roles/zammad/files/zammad_agent_write_readback.rb"
VERIFY = "roles/zammad/tasks/verify_agent_write_rights.yml"
BOOTSTRAP_TASKS = "roles/zammad/tasks/main/nginx_and_bootstrap.yml"

# In-memory stand-ins for the Zammad models the readback reads.
HARNESS = r"""
require 'json'
require 'time'
Named = Struct.new(:name)
class Role
  attr_reader :name, :permissions
  def initialize(name, permissions); @name = name; @permissions = permissions.map { |p| Named.new(p) }; end
  ROWS = [new('Agent', %w[ticket.agent knowledge_base.editor]), new('Admin', %w[admin])]
  def self.where(cond); ROWS.select { |r| r.name == cond[:name] }; end
end
class Group
  NAMES = %w[Incidents Changes]
  def self.exists?(cond); NAMES.include?(cond[:name]); end
end
class User
  attr_reader :email, :login, :roles, :group_names_access_map
  def initialize(email, roles, access); @email = email; @login = email; @roles = roles; @group_names_access_map = access; end
  ROWS = [new('svc-agent-write@example.test', [Role::ROWS[0]], { 'Incidents' => %w[read create change] }),
          new('svc-ai@example.test', [Role::ROWS[0]], {})]
  def self.where(cond); ROWS.select { |u| u.email == cond[:email] }; end
end
class Token
  attr_reader :id, :action, :name, :token, :user, :last_used_at
  def initialize(id, name, user, last_used); @id = id; @action = 'api'; @name = name; @token = "fixture-secret-#{id}"; @user = user; @last_used_at = last_used; end
  ROWS = [new(2, 'ai', User::ROWS[1], Time.utc(2026, 11, 19, 8, 30, 0)),
          new(1, 'agent-write', User::ROWS[0], nil),
          new(3, 'old triage token', nil, nil)]
  class Query
    def initialize(rows); @rows = rows; end
    def order(key); @rows.sort_by { |r| r.public_send(key) }; end
  end
  def self.where(cond); Query.new(ROWS.select { |r| r.action == cond[:action] }); end
end
load ARGV[0]
"""


def _run(tmp_path, env_overrides=None) -> subprocess.CompletedProcess:
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("ruby is not available in this environment")
    (tmp_path / "harness.rb").write_text(HARNESS, encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "ZAMMAD_AGENT_WRITE_EMAIL": "svc-agent-write@example.test",
        "ZAMMAD_AGENT_WRITE_GROUPS": json.dumps(["Incidents", "Missing"]),
        **(env_overrides or {}),
    }
    return subprocess.run(
        [ruby, str(tmp_path / "harness.rb"), str(READBACK)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


def test_the_readback_prints_one_names_only_line(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    (line,) = result.stdout.splitlines()
    assert line.startswith("ZAMMAD_AGENT_WRITE_READBACK=")
    assert "fixture-secret" not in result.stdout
    readback = json.loads(line.split("=", 1)[1])
    assert readback == {
        "agent_role_count": 1,
        "agent_role_permissions": ["knowledge_base.editor", "ticket.agent"],
        "user_count": 1,
        "user_roles": ["Agent"],
        "user_group_access": {"Incidents": ["change", "create", "read"]},
        "declared_groups_present": ["Incidents"],
        "api_rows": [
            {"name": "agent-write", "owner": "svc-agent-write@example.test", "last_used_at": None},
            {"name": "ai", "owner": "svc-ai@example.test", "last_used_at": "2026-11-19T08:30:00Z"},
            {"name": "old triage token", "owner": "", "last_used_at": None},
        ],
    }


def test_the_verification_uses_no_administrator_credential():
    text = (ROOT / VERIFY).read_text(encoding="utf-8")
    for credential in ("zammad_admin_password", "zammad_admin_email", "force_basic_auth"):
        assert credential not in text
    verification = _yaml(VERIFY)
    read = _task(verification, "Read the agent-write rights and API rows through rails")
    assert set(read["environment"]) == {"ZAMMAD_AGENT_WRITE_EMAIL", "ZAMMAD_AGENT_WRITE_GROUPS"}
    assert read["changed_when"] is False


def test_the_api_rows_are_shown_names_only():
    show = _task(_yaml(BOOTSTRAP_TASKS), "Show the Zammad API rows (names only)")
    assert show["no_log"] is False
    assert show["when"] == "not ansible_check_mode"

    def shown(rows):
        return _render(
            show["ansible.builtin.debug"]["msg"],
            {**show["vars"], "zammad_agent_write_readback": {"api_rows": rows}},
        )

    good = [
        {"name": "ai-rotation-20261105", "owner": "svc-ai@example.test", "last_used_at": "2026-11-10T21:31:35Z"},
        {"name": "old triage token", "owner": "", "last_used_at": None},
    ]
    assert shown(good) == [
        "ai-rotation-20261105 owner=svc-ai@example.test last_used=2026-11-10T21:31:35Z",
        "old triage token owner=- last_used=never",
    ]
    assert shown(
        [
            {"name": "x\nfixture-secret", "owner": "svc@example.test", "last_used_at": None},
            {"name": "ok", "owner": "svc@example.test", "last_used_at": "fixture-secret"},
            {"name": "ok", "owner": {"nested": "fixture-secret"}, "last_used_at": None},
        ]
    ) == []
    assert shown([]) == []
