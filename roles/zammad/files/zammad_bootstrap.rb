# Idempotent Zammad bootstrap — run via `zammad run rails r zammad_bootstrap.rb`.
# All inputs arrive as ENV (set by the Ansible task's `environment:`) so nothing
# secret is ever on a command line. Prints "ZAMMAD_BOOTSTRAP_CHANGED" whenever it
# mutates state, so the Ansible task can report changed accurately; a re-run with
# no drift prints nothing and stays idempotent.
#
# Essential seeding (settings, admin, API token, Incidents group, severities)
# fails loudly. The version-sensitive extras (Mailpit notification channel, the
# knowledge base) are wrapped so a model-API drift warns but never aborts the
# converge — both have a one-click manual fallback in the UI.

changed = false
UserInfo.current_user_id = 1 # act as the system user for created_by/updated_by

def env!(key)
  v = ENV[key]
  raise "missing required env #{key}" if v.nil? || v.empty?
  v
end

fqdn        = env!('ZAMMAD_FQDN')
es_url      = env!('ZAMMAD_ES_URL')
admin_email = env!('ZAMMAD_ADMIN_EMAIL')
admin_pass  = env!('ZAMMAD_ADMIN_PASSWORD')
api_token   = env!('ZAMMAD_API_TOKEN')
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

# --- Incident groups (create-or-find; make admin a full agent in each) -------
groups.each do |gname|
  group = Group.find_by(name: gname)
  if group.nil?
    group = Group.create!(name: gname, active: true)
    changed = true
  end
  # Grant the admin full access to the group so it can own/route incidents.
  unless admin.group_ids_access('full').include?(group.id)
    admin.group_names_access_map = admin.group_names_access_map.merge(group.name => ['full'])
    admin.save!
    changed = true
  end
end

# --- Severity: keep built-in 1 low / 2 normal / 3 high, add 4 critical -------
if Ticket::Priority.find_by(id: 4).nil? && Ticket::Priority.find_by(name: '4 critical').nil?
  Ticket::Priority.create!(id: 4, name: '4 critical', active: true)
  changed = true
end

# --- Hermes API token (persistent api token seeded with the supplied value) --
if Token.find_by(action: 'api', name: 'hermes').nil?
  Token.create!(action: 'api', name: 'hermes', persistent: true, user_id: admin.id, token: api_token)
  changed = true
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

puts 'ZAMMAD_BOOTSTRAP_CHANGED' if changed
