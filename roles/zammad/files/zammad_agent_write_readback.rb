# Read-only readback for the agent-write rights verification, run with
# `zammad run rails r` after the bootstrap. It writes nothing and prints one
# line of names only: role, group and API row names, never a token value.
require 'json'
require 'time'

agent_write_email = ENV.fetch('ZAMMAD_AGENT_WRITE_EMAIL')
declared_groups = JSON.parse(ENV.fetch('ZAMMAD_AGENT_WRITE_GROUPS'))

agent_roles = Role.where(name: 'Agent').to_a
users = User.where(email: agent_write_email).to_a
user = users.first

readback = {
  'agent_role_count' => agent_roles.size,
  'agent_role_permissions' => agent_roles.size == 1 ? agent_roles.first.permissions.map(&:name).sort : [],
  'user_count' => users.size,
  'user_roles' => user ? user.roles.map(&:name).sort : [],
  'user_group_access' => user ? user.group_names_access_map.transform_values { |access| Array(access).sort } : {},
  'declared_groups_present' => declared_groups.select { |name| Group.exists?(name: name) },
  'api_rows' => Token.where(action: 'api').order(:id).map do |row|
    last_used = row.respond_to?(:last_used_at) ? row.last_used_at : nil
    { 'name' => row.name.to_s, 'owner' => (row.user&.login).to_s, 'last_used_at' => last_used&.utc&.iso8601 }
  end,
}
puts "ZAMMAD_AGENT_WRITE_READBACK=#{readback.to_json}"
