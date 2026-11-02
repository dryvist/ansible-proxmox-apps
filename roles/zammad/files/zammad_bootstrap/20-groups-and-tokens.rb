# Top-level org holds the humans + the interactive-AI account; hermes gets its
# OWN non-shared org so its 24/7 auto-filed tickets live in a separate
# container (filter, bulk-manage, or purge them without touching the rest).
hermes_user, ai_user = service_users
org_name = ENV['ZAMMAD_ORGANIZATION']
if org_name && !org_name.empty?
  org = Organization.find_by(name: org_name)
  if org.nil?
    org = Organization.create!(name: org_name, shared: true, active: true)
    changed = true
  end
  [admin, ai_user].each do |u|
    next if u.organization_id == org.id
    u.update!(organization_id: org.id)
    changed = true
  end
end

hermes_org_name = ENV['ZAMMAD_HERMES_ORGANIZATION']
if hermes_org_name && !hermes_org_name.empty?
  hermes_org = Organization.find_by(name: hermes_org_name)
  if hermes_org.nil?
    hermes_org = Organization.create!(name: hermes_org_name, shared: false, active: true,
                                      note: 'Container for tickets auto-filed by the Hermes agent')
    changed = true
  end
  unless hermes_user.organization_id == hermes_org.id
    hermes_user.update!(organization_id: hermes_org.id)
    changed = true
  end
end

# --- Incident groups (create-or-find; admin + service users get full access) -
# Deliberately broad, including for svc-splunk: do NOT narrow this to the one
# group Splunk alerts default to. `action.zammad.param.group` is a per-search
# override, so a narrow grant 403s the first time a detector points elsewhere,
# and that failure surfaces as an incident that was never opened -- silent alert
# loss, discovered during the outage it should have reported. Least privilege is
# enforced on the token's scopes instead (see splunk_prefs below).
groups.each do |gname|
  group = Group.find_by(name: gname)
  if group.nil?
    group = Group.create!(name: gname, active: true)
    changed = true
  end
  ([admin] + service_users).each do |u|
    next if u.group_ids_access('full').include?(group.id)
    u.group_names_access_map = u.group_names_access_map.merge(group.name => ['full'])
    u.save!
    changed = true
  end
end

# --- Severity: keep built-in 1 low / 2 normal / 3 high, add 4 critical -------
if Ticket::Priority.find_by(id: 4).nil? && Ticket::Priority.find_by(name: '4 critical').nil?
  Ticket::Priority.create!(id: 4, name: '4 critical', active: true)
  changed = true
end

# --- API tokens (persistent, seeded with supplied values; reconciled on
# rotation in OpenBao/Doppler). Each token belongs to ITS OWN service user —
# never the admin — and carries only Agent-level scopes.
# Two hard-won constraints (first live bring-up, 2026-07-16):
#   1. Token.create!/update! REGENERATE the token value via callbacks —
#      update_column is the only way the supplied secret actually persists,
#      so the value is re-asserted LAST, after any update!.
#   2. An api token with empty preferences has NO permission scopes and every
#      HTTP request is rejected "Authentication required".
#   3. Scopes ride the TOKEN's preferences, not the user's roles -- which is the
#      real mechanism behind "this credential 401s on create". A token whose
#      preferences omit a scope is rejected however privileged its user is, so
#      least privilege is set here rather than by trimming roles.
agent_prefs = { 'permission' => %w[ticket.agent knowledge_base.editor] }
# svc-splunk creates tickets, appends articles, and searches by title for the
# dedup lookup. ticket.agent is the smallest permission that covers all three --
# Zammad has no finer split -- and knowledge_base.editor is withheld because the
# alert action has no use for it. svc-ntfy gets the same scope as svc-splunk:
# it opens tickets, appends articles, closes on a resolved tag, and searches
# by title for the dedup lookup -- no knowledge_base use either.
splunk_prefs = { 'permission' => %w[ticket.agent] }
ntfy_prefs = { 'permission' => %w[ticket.agent] }
# svc-cribl only creates tickets (dedup happens in the pipeline's Suppress).
cribl_prefs = { 'permission' => %w[ticket.agent] }
agent_write_prefs = { 'permission' => %w[ticket.agent] }
[
  ['hermes', service_users[0], api_token, agent_prefs],
  ['ai', service_users[1], ai_api_token, agent_prefs],
  ['splunk', service_users[2], splunk_api_token, splunk_prefs],
  ['ntfy', service_users[3], ntfy_api_token, ntfy_prefs],
  ['cribl', service_users[4], cribl_api_token, cribl_prefs],
  ['agent-write', service_users[5], agent_write_api_token, agent_write_prefs],
].each do |name, user, value, token_prefs|
  t = Token.find_by(action: 'api', name: name)
  if t.nil?
    t = Token.create!(action: 'api', name: name, persistent: true,
                      user_id: user.id, preferences: token_prefs)
    changed = true
  elsif t.user_id != user.id || t.preferences != token_prefs || !t.persistent
    t.update!(user_id: user.id, preferences: token_prefs, persistent: true)
    changed = true
  end
  if t.token != value
    t.update_column(:token, value)
    changed = true
  end
end
