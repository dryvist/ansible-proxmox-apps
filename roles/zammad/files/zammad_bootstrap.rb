# Idempotent Zammad bootstrap — run via `zammad run rails r zammad_bootstrap.rb`.
# All inputs arrive as ENV (set by the Ansible task's `environment:`) so nothing
# secret is ever on a command line. Prints "ZAMMAD_BOOTSTRAP_CHANGED" whenever it
# mutates state, so the Ansible task can report changed accurately; a re-run with
# no drift prints nothing and stays idempotent.
#
# Essential seeding (settings, admin, per-actor service accounts + API tokens,
# Incidents group, severities) fails loudly. The version-sensitive extras
# (Mailpit notification channel, knowledge base) are wrapped so a model-API
# drift warns but never aborts the converge — both have a one-click manual
# fallback in the UI.

changed = false
UserInfo.current_user_id = 1 # act as the system user for created_by/updated_by

def env!(key)
  v = ENV[key]
  raise "missing required env #{key}" if v.nil? || v.empty?
  v
end

fqdn         = env!('ZAMMAD_FQDN')
es_url       = env!('ZAMMAD_ES_URL')
admin_email  = env!('ZAMMAD_ADMIN_EMAIL')
admin_pass   = env!('ZAMMAD_ADMIN_PASSWORD')
api_token    = env!('ZAMMAD_API_TOKEN')
ai_api_token = env!('ZAMMAD_AI_API_TOKEN')
hermes_email = env!('ZAMMAD_HERMES_EMAIL')
ai_email     = env!('ZAMMAD_AI_EMAIL')
smtp_host   = env!('ZAMMAD_SMTP_HOST')
smtp_port   = env!('ZAMMAD_SMTP_PORT').to_i
sender      = env!('ZAMMAD_NOTIFICATION_SENDER')
groups      = env!('ZAMMAD_GROUPS').split(',').map(&:strip).reject(&:empty?)

def set_setting(name, value)
  return false if Setting.get(name) == value
  Setting.set(name, value)
  true
end

# --- Core settings: end the getting-started wizard, https, storage, es -------
{
  'system_init_done' => true,
  'fqdn'             => fqdn,
  'http_type'       => 'https',
  'storage_provider' => 'File',
  'es_url'          => es_url,
}.each { |k, v| changed = true if set_setting(k, v) }

# --- Admin user (create-or-find; ensure Admin+Agent + active) ----------------
admin = User.find_by(email: admin_email.downcase)
roles = Role.where(name: %w[Admin Agent]).to_a
if admin.nil?
  admin = User.create!(
    login: admin_email.downcase, firstname: ENV['ZAMMAD_ADMIN_FIRSTNAME'] || 'Zammad',
    lastname: ENV['ZAMMAD_ADMIN_LASTNAME'] || 'Admin', email: admin_email.downcase,
    password: admin_pass, roles: roles, active: true
  )
  changed = true
else
  missing = roles - admin.roles.to_a
  unless missing.empty?
    admin.roles = (admin.roles.to_a + missing).uniq
    admin.save!
    changed = true
  end
end

# --- Dedicated AI service accounts (per-actor audit trail) -------------------
# Every machine actor gets its OWN Agent-role user so the activity stream and
# ticket history attribute writes to the real actor — the admin account stays
# human-only. No password is set: these accounts are API-token-only and cannot
# log in via the web UI.
agent_role = [Role.find_by!(name: 'Agent')]
# hermes also carries Customer: the zammad-incidents skill omits the customer
# field, so Zammad makes the token's user the ticket customer — which routes
# every Hermes-filed ticket into the dedicated Hermes org (blast-radius
# isolation for a 24/7 autonomous filer).
hermes_roles = [Role.find_by!(name: 'Agent'), Role.find_by!(name: 'Customer')]
service_users = [
  [hermes_email, 'Hermes', 'Agent', hermes_roles],
  [ai_email, 'AI', 'Assistant', agent_role],
].map do |email, first, last, desired_roles|
  u = User.find_by(email: email.downcase)
  if u.nil?
    u = User.create!(login: email.downcase, firstname: first, lastname: last,
                     email: email.downcase, roles: desired_roles, active: true)
    changed = true
  elsif u.role_ids.sort != desired_roles.map(&:id).sort || !u.active
    # Reconcile drift: service accounts carry exactly their desired roles and
    # stay active — strip any elevated role that snuck on outside this
    # bootstrap.
    u.update!(roles: desired_roles, active: true)
    changed = true
  end
  u
end

# Agents need knowledge_base.editor for their tokens to carry that scope; the
# default Agent role does not always include it.
kb_perm = Permission.find_by(name: 'knowledge_base.editor')
if kb_perm && !agent_role.first.permissions.include?(kb_perm)
  agent_role.first.permissions << kb_perm
  changed = true
end

# --- Organizations ------------------------------------------------------------
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
token_prefs = { 'permission' => %w[ticket.agent knowledge_base.editor] }
[
  ['hermes', service_users[0], api_token],
  ['ai', service_users[1], ai_api_token],
].each do |name, user, value|
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

# --- Outbound email via the Mailpit relay (best-effort; manual UI fallback) --
begin
  channel = Channel.find_by(area: 'Email::Notification')
  desired = {
    adapter: 'smtp', host: smtp_host, port: smtp_port,
    ssl: false, start_tls: false, user: '', password: ''
  }
  if channel.nil?
    Channel.create!(
      area: 'Email::Notification', group_id: Group.first&.id,
      options: { outbound: { adapter: 'smtp', options: desired } }, active: true
    )
    changed = true
  elsif channel.options.dig('outbound', 'options', 'host') != smtp_host
    channel.options = { 'outbound' => { 'adapter' => 'smtp', 'options' => desired.transform_keys(&:to_s) } }
    channel.save!
    changed = true
  end
  changed = true if set_setting('notification_sender', sender)
rescue => e
  warn "WARN: Mailpit notification channel not configured automatically (#{e.class}: #{e.message}). Configure it once in the UI."
end

# --- Knowledge base (best-effort; manual UI fallback) ------------------------
begin
  if defined?(KnowledgeBase) && KnowledgeBase.count.zero?
    kb = KnowledgeBase.create!(
      iconset: 'FontAwesome', color_highlight: '#38ae6a', color_header: '#f9fafb',
      homepage_layout: 'grid', category_layout: 'grid', active: true, translations: []
    )
    kb.kb_locales.create!(kb_locale: 'en-us', primary: true) if kb.respond_to?(:kb_locales)
    changed = true
  end
rescue => e
  warn "WARN: knowledge base not created automatically (#{e.class}: #{e.message}). Create it once in the UI."
end

# --- Overviews: saved filtered views, defined as DATA in zammad_overviews ----
# (role defaults, ZAMMAD_OVERVIEWS json env). Idempotent by name. Each entry's
# small declarative keys (open_only, priority_ids, tag, updated_within_days)
# map onto Zammad's Overview condition schema here, so the YAML stays free of
# Zammad internals.
begin
  require 'json'
  overviews = JSON.parse(ENV['ZAMMAD_OVERVIEWS'] || '[]')
  overview_agent_role = Role.find_by!(name: 'Agent')
  overview_view = {
    'd' => %w[title customer group state priority created_at],
    's' => %w[title customer group state priority created_at],
    'm' => %w[number title customer group state priority created_at],
    'view_mode_default' => 's',
  }
  overviews.each do |ov|
    next if Overview.exists?(name: ov['name'])
    condition = {}
    if ov['open_only']
      condition['ticket.state_id'] =
        { 'operator' => 'is', 'value' => Ticket::State.by_category(:open).pluck(:id) }
    end
    if ov['priority_ids']
      condition['ticket.priority_id'] = { 'operator' => 'is', 'value' => ov['priority_ids'] }
    end
    if ov['tag']
      condition['ticket.tags'] = { 'operator' => 'contains one', 'value' => ov['tag'] }
    end
    if ov['updated_within_days']
      condition['ticket.updated_at'] =
        { 'operator' => 'within last (relative)', 'range' => 'day', 'value' => ov['updated_within_days'] }
    end
    if ov['organization']
      ov_org = Organization.find_by(name: ov['organization'])
      if ov_org.nil?
        warn "WARN: organization '#{ov['organization']}' not found — skipping overview '#{ov['name']}'."
        next
      end
      condition['ticket.organization_id'] = { 'operator' => 'is', 'value' => [ov_org.id] }
    end
    Overview.create!(
      name: ov['name'], link: ov['link'], prio: ov['prio'], condition: condition,
      order: { 'by' => ov['order_by'], 'direction' => ov['order_direction'] },
      roles: [overview_agent_role], user_ids: [], view: overview_view
    )
    changed = true
  end
rescue => e
  warn "WARN: overviews not seeded automatically (#{e.class}: #{e.message}). Create them once in the UI."
end

puts 'ZAMMAD_BOOTSTRAP_CHANGED' if changed
