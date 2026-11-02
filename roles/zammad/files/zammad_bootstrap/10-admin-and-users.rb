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

# --- Human SSO account (Authelia forwardAuth identity) -----------------------
# Zammad looks the user up by LOGIN (User.lookup(login: login&.downcase)), so
# the login MUST equal the Authelia username verbatim — the email is metadata,
# not the lookup key. No password is set: this account authenticates only by the
# SSO header, and admin@ stays the break-glass password login for when Authelia
# itself is down.
sso_roles = Role.where(name: %w[Admin Agent]).to_a
sso_user = User.find_by(login: sso_login.downcase)
if sso_user.nil?
  sso_user = User.create!(
    login: sso_login.downcase, firstname: sso_first, lastname: sso_last,
    email: sso_email.downcase, roles: sso_roles, active: true
  )
  changed = true
else
  missing_sso = sso_roles - sso_user.roles.to_a
  if !missing_sso.empty? || !sso_user.active
    sso_user.roles = (sso_user.roles.to_a + missing_sso).uniq
    sso_user.active = true
    sso_user.save!
    changed = true
  end
end

# --- Dedicated AI service accounts (per-actor audit trail) -------------------
# Every machine actor gets its OWN Agent-role user so the activity stream and
# ticket history attribute writes to the real actor — the admin account stays
# human-only. No password is set: these accounts are API-token-only and cannot
# log in via the web UI.
# The built-in Agent role is shared by the service accounts. Pin its complete
# permission set so an upstream/default or manual grant cannot widen them.
agent_role_permission_names = %w[ticket.agent knowledge_base.editor]
agent_role_record = Role.find_by!(name: 'Agent')
agent_role_permissions = agent_role_permission_names.map do |name|
  Permission.find_by!(name: name)
end
unless agent_role_record.permissions.map(&:name).sort == agent_role_permission_names.sort
  agent_role_record.permissions = agent_role_permissions
  agent_role_record.save!
  changed = true
end
agent_role = [agent_role_record]
# hermes also carries Customer: the zammad-incidents skill omits the customer
# field, so Zammad makes the token's user the ticket customer — which routes
# every Hermes-filed ticket into the dedicated Hermes org (blast-radius
# isolation for a 24/7 autonomous filer).
hermes_roles = [Role.find_by!(name: 'Agent'), Role.find_by!(name: 'Customer')]
# svc-splunk also carries Customer, for the same reason hermes does: the Splunk
# alert action omits the customer field, so Zammad makes the token's user the
# ticket customer. That keeps Splunk-opened incidents attributable to Splunk
# without the action having to invent or provision a customer.
splunk_roles = [Role.find_by!(name: 'Agent'), Role.find_by!(name: 'Customer')]
# svc-ntfy: same reasoning as svc-splunk — the ntfy-zammad subscriber (ntfy CLI
# `command:` hook) omits the customer field too, so its token's user becomes
# the ticket customer.
ntfy_roles = [Role.find_by!(name: 'Agent'), Role.find_by!(name: 'Customer')]
# svc-cribl: same again -- Cribl Edge's zammad_security_ids webhook omits the
# customer, so its token's user becomes the customer of every IDS ticket.
cribl_roles = [Role.find_by!(name: 'Agent'), Role.find_by!(name: 'Customer')]
service_users = [
  [hermes_email, 'Hermes', 'Agent', hermes_roles],
  [ai_email, 'AI', 'Assistant', agent_role],
  [splunk_email, 'Splunk', 'Alerting', splunk_roles],
  [ntfy_email, 'ntfy', 'Alerting', ntfy_roles],
  [cribl_email, 'Cribl', 'Alerting', cribl_roles],
  [agent_write_email, 'Service', 'Agent Write', agent_role],
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

# --- Organizations ------------------------------------------------------------
