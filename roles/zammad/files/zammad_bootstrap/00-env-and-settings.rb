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
agent_write_email = env!('ZAMMAD_AGENT_WRITE_EMAIL')
agent_write_api_token = env!('ZAMMAD_AGENT_WRITE_API_TOKEN')
splunk_email = env!('ZAMMAD_SPLUNK_EMAIL')
splunk_api_token = env!('ZAMMAD_SPLUNK_API_TOKEN')
ntfy_email = env!('ZAMMAD_NTFY_EMAIL')
ntfy_api_token = env!('ZAMMAD_NTFY_API_TOKEN')
cribl_email = env!('ZAMMAD_CRIBL_EMAIL')
cribl_api_token = env!('ZAMMAD_CRIBL_API_TOKEN')
smtp_host   = env!('ZAMMAD_SMTP_HOST')
smtp_port   = env!('ZAMMAD_SMTP_PORT').to_i
sender      = env!('ZAMMAD_NOTIFICATION_SENDER')
groups      = env!('ZAMMAD_GROUPS').split(',').map(&:strip).reject(&:empty?)
sso_login   = env!('ZAMMAD_SSO_LOGIN')
sso_email   = env!('ZAMMAD_SSO_EMAIL')
sso_first   = env!('ZAMMAD_SSO_FIRSTNAME')
sso_last    = env!('ZAMMAD_SSO_LASTNAME')
sso_ips     = env!('ZAMMAD_SSO_TRUSTED_IPS')

def set_setting(name, value)
  return false if Setting.get(name) == value
  Setting.set(name, value)
  true
end

# --- Core settings: end the getting-started wizard, https, storage, es -------
# auth_sso: Zammad's SessionsController#create_sso reads the login from
# request.env REMOTE_USER / HTTP_REMOTE_USER / X-Forwarded-User, so Authelia's
# `Remote-User` forwardAuth header lands as HTTP_REMOTE_USER and logs the user
# in with no password. Traefik STRIPS any client-supplied Remote-* header before
# forwardAuth (roles/traefik), which is what makes trusting this header safe —
# without that strip anyone could assert any login here, so the two ship together.
#
# auth_sso_trusted_ips is a hard requirement, not defence in depth: Zammad's
# verify_sso_trusted_ip! does `return if trusted_ips.blank?` — a blank value
# skips the source check entirely.
{
  'system_init_done' => true,
  'fqdn'             => fqdn,
  'http_type'       => 'https',
  'storage_provider' => 'File',
  # Hard-set the system identifier to 1. Zammad assigns a random id (1-99) at
  # install (this instance drew 17); pin it so the ticket-number prefix is
  # deterministic across rebuilds. Stored as an Integer — set_setting compares
  # Setting.get('system_id') (Integer) to this, so a re-run is a no-op.
  'system_id'       => 1,
  'es_url'          => es_url,
  'auth_sso'        => true,
  # A comma-separated STRING, never an Array: Auth::Sso::TrustedIps does
  # `setting_value.to_s.split(',')`, so an Array stringifies to `["a", "b"]` and
  # every entry then fails IPAddr parsing — include? returns false and SSO is
  # rejected for everyone. CIDR entries are supported.
  'auth_sso_trusted_ips' => sso_ips.split(',').map(&:strip).reject(&:empty?).join(','),
}.each { |k, v| changed = true if set_setting(k, v) }

# --- Declared settings (data-driven, from zammad_settings) -------------------
# Every Setting the role owns beyond the core block above arrives as ONE JSON
# object, so adding a knob is a defaults/group_vars edit and never a change
# here. Values are applied verbatim, so the YAML carries Zammad's own types
# (Integer, Array, String). Nothing in this path deletes data.
JSON.parse(ENV['ZAMMAD_SETTINGS'] || '{}').each do |name, value|
  changed = true if set_setting(name, value)
end

# --- Retention: keep the history, stop the sweepers --------------------------
# Zammad ships Scheduler rows that DELETE historical rows on a timer (activity
# stream entries, HTTP request logs). Traceability is worth more than the disk
# they reclaim here, so the named jobs are deactivated. Only the `active` flag
# is touched — no job is removed, and re-enabling one is a defaults edit.
JSON.parse(ENV['ZAMMAD_DISABLED_SCHEDULERS'] || '[]').each do |job_name|
  job = Scheduler.find_by(name: job_name)
  if job.nil?
    warn "WARN: scheduler #{job_name.inspect} not found — skipping (name drift?)"
    next
  end
  next unless job.active

  job.update!(active: false)
  changed = true
end

# Zammad's own built-in Scheduler ("Process pending tickets.", Ticket.
# process_pending) must stay active — it is what actually moves a `pending
# close` ticket to its next state, and the "Pending close" overview is only
# useful while it does. Never named in ZAMMAD_DISABLED_SCHEDULERS above; assert
# it explicitly so a future edit there can't silently take it down.
pending_scheduler = Scheduler.find_by(name: 'Process pending tickets.')
raise "missing built-in scheduler 'Process pending tickets.' — Zammad version drift?" if pending_scheduler.nil?

if !pending_scheduler.active
  pending_scheduler.update!(active: true)
  changed = true
end

# --- GitHub issue-linking (opt-in) -------------------------------------------
# Enabled only when ZAMMAD_CONFIGURE_GITHUB=true AND a token is present. The
# token is minted per converge from the OpenBao github engine (github/token/
# read-*), never seeded into KV. Best-effort: github_config runs verify!, which
# reaches out to the GitHub API and can take a moment.
if ENV['ZAMMAD_CONFIGURE_GITHUB'] == 'true' && !ENV['ZAMMAD_GITHUB_API_TOKEN'].to_s.empty?
  begin
    changed = true if set_setting('github_config', {
      'endpoint'  => env!('ZAMMAD_GITHUB_ENDPOINT'),
      'api_token' => env!('ZAMMAD_GITHUB_API_TOKEN'),
    })
    changed = true if set_setting('github_integration', true)
  rescue => e
    warn "WARN: GitHub integration not configured (#{e.class}: #{e.message}). Set it once in Admin -> Integrations -> GitHub."
  end
end
