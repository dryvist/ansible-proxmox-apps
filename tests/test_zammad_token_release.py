"""A declared Zammad API token value held by another row is released, then set.

The token column is unique. The bootstrap gives any other api row holding a
declared value a random token (the row stays), prints a names-only line, and
then sets every declared value; a swapped pair resolves in the same run.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from app_agent_helpers import ROOT, _render, _task, _yaml

FRAGMENT = ROOT / "roles/zammad/files/zammad_bootstrap/20-groups-and-tokens.rb"
BOOTSTRAP_TASKS = "roles/zammad/tasks/main/nginx_and_bootstrap.yml"

# An in-memory Token model with Zammad's unique token rule, the declared
# inputs, and a stale row plus a swapped declared pair holding declared values.
HARNESS = r"""
require 'json'
module ActiveRecord; class RecordNotUnique < StandardError; end; end
class Token
  ROWS = []
  attr_accessor :id, :action, :name, :token, :user_id, :preferences, :persistent
  def initialize(attrs); attrs.each { |k, v| public_send("#{k}=", v) }; end
  def self.seed(attrs)
    row = new({ id: ROWS.size + 1, action: 'api', persistent: true, preferences: {} }.merge(attrs))
    ROWS << row
    row
  end
  def self.where(cond); ROWS.select { |r| cond.all? { |k, v| r.public_send(k) == v } }; end
  def self.find_by(cond); where(cond).first; end
  def self.find_by!(cond); find_by(cond) or raise 'not found'; end
  def self.create!(attrs); seed(attrs.merge(token: "generated-#{ROWS.size + 1}")); end
  def update!(attrs)
    attrs.each { |k, v| public_send("#{k}=", v) }
    self.token = "regenerated-#{id}"
    self
  end
  def update_column(column, value)
    if column == :token && ROWS.any? { |r| r.id != id && r.action == action && r.token == value }
      raise ActiveRecord::RecordNotUnique
    end
    public_send("#{column}=", value)
  end
  def reload; self; end
end
User = Struct.new(:id, :email)
service_users = (1..5).map { |i| User.new(i, "svc#{i}@example.test") }
agent_write_user = User.new(6, 'agent-write@example.test')
triage_user = User.new(7, 'triage@example.test')
clerk_user = User.new(8, 'clerk@example.test')
api_token, ai_api_token, splunk_api_token, ntfy_api_token, cribl_api_token, agent_write_api_token,
  triage_api_token, clerk_api_token =
  %w[hermes ai splunk ntfy cribl agent-write zammad-triage zammad-clerk].map { |n| "fixture-secret-#{n}" }
agent = { 'permission' => %w[ticket.agent knowledge_base.editor] }
Token.seed(name: 'hermes', user_id: 1, token: api_token, preferences: agent)
Token.seed(name: 'ai', user_id: 2, token: agent_write_api_token, preferences: agent)
Token.seed(name: 'agent-write', user_id: 6, token: ai_api_token, preferences: { 'permission' => %w[ticket.agent] })
Token.seed(name: 'old triage token', user_id: 1, token: splunk_api_token)
Token.seed(name: 'cribl', user_id: 5, token: 'fixture-secret-old-cribl', preferences: { 'permission' => %w[ticket.agent] })
changed = false
slice = File.read(ARGV[0])
eval(slice, binding)
puts 'SECOND_RUN'
eval(slice, binding)
File.write(ARGV[1], JSON.generate(Token::ROWS.map { |r| [r.name, r.token] }))
"""


def _run(tmp_path) -> tuple[subprocess.CompletedProcess, list]:
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("ruby is not available in this environment")
    fragment = FRAGMENT.read_text(encoding="utf-8")
    (tmp_path / "slice.rb").write_text(fragment[fragment.index("agent_prefs = {") :], encoding="utf-8")
    (tmp_path / "harness.rb").write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        [ruby, str(tmp_path / "harness.rb"), str(tmp_path / "slice.rb"), str(tmp_path / "rows.json")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    rows = json.loads((tmp_path / "rows.json").read_text()) if result.returncode == 0 else []
    return result, rows


def test_a_stale_holder_and_a_swapped_pair_are_released_then_set(tmp_path):
    result, rows = _run(tmp_path)
    assert result.returncode == 0, result.stderr

    first, second = result.stdout.split("SECOND_RUN\n")
    released = [line for line in first.splitlines() if line.startswith("ZAMMAD_BOOTSTRAP_RELEASED")]
    assert released == [
        "ZAMMAD_BOOTSTRAP_RELEASED name=ai holder=agent-write",
        "ZAMMAD_BOOTSTRAP_RELEASED name=splunk holder=old_triage_token",
        "ZAMMAD_BOOTSTRAP_RELEASED name=agent-write holder=ai",
    ]
    assert "fixture-secret" not in result.stdout
    assert "ZAMMAD_BOOTSTRAP_RELEASED" not in second

    declared = {name: f"fixture-secret-{name}" for name in ("hermes", "ai", "splunk", "ntfy", "cribl", "agent-write")}
    by_name = dict(rows)
    assert {name: by_name[name] for name in declared} == declared
    stale = by_name["old triage token"]
    assert stale not in declared.values() and len(stale) == 64
    assert len({token for _, token in rows}) == len(rows)


def test_the_release_lines_are_shown_success_or_failure():
    block = _task(_yaml(BOOTSTRAP_TASKS), "Run the Zammad bootstrap and name the failing fragment on failure")
    (show,) = block["always"]
    assert show["no_log"] is False

    def shown(lines):
        return _render(show["ansible.builtin.debug"]["msg"], {**show["vars"], "zammad_bootstrap": {"stdout_lines": lines}})

    good = "ZAMMAD_BOOTSTRAP_RELEASED name=agent-write holder=old_triage_token"
    assert shown([good, "ZAMMAD_BOOTSTRAP_CHANGED"]) == [good]
    assert shown(
        [
            f"{good} fixture-secret-value",
            "ZAMMAD_BOOTSTRAP_RELEASED name=other holder=x",
            "ZAMMAD_BOOTSTRAP_RELEASED name=ai holder=has space",
        ]
    ) == []
    assert shown([]) == []
