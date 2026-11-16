# --- Webhooks + Triggers: outbound notifications, defined as DATA -------------
# (role defaults, ZAMMAD_WEBHOOKS / ZAMMAD_TRIGGERS json env). Both default to
# empty lists and this section then does nothing at all — not even a model
# touch. Idempotent by name: create when absent, update only fields that differ
# from the declared entry, and never touch or delete objects not named in the
# variables.
#
# A trigger performs ONLY its webhook action: the perform hash is built here
# from the declared webhook's Zammad id, never read from variables, so a
# trigger seeded from this section can never carry another action.
#
# Unlike the best-effort sections above, problems here RAISE and fail the
# play, before any Webhook/Trigger row is written: an endpoint that is not
# https://, a custom_payload that is not valid JSON once the product's ticket
# placeholders are replaced, a trigger naming a webhook this run does not
# declare, and a Webhook model lacking the custom-payload or bearer-token
# attributes (version drift — Zammad gains attributes, never loses them).
require 'json'

webhooks = JSON.parse(ENV['ZAMMAD_WEBHOOKS'] || '[]')
triggers = JSON.parse(ENV['ZAMMAD_TRIGGERS'] || '[]')

if webhooks.any? || triggers.any?
  ticket_placeholder = Regexp.new(Regexp.escape('#{') + '[^}]*' + Regexp.escape('}'))

  # --- Validate everything first; nothing below is written on any failure ----
  webhooks.each do |declared|
    raise "zammad_webhooks entry '#{declared['name']}': 'name' is required" if declared['name'].to_s.empty?
    unless declared['endpoint'].to_s.start_with?('https://')
      raise "zammad_webhooks entry '#{declared['name']}': 'endpoint' must start with https://"
    end
    next unless declared['custom_payload']
    begin
      JSON.parse(declared['custom_payload'].gsub(ticket_placeholder, 'PLACEHOLDER'))
    rescue JSON::ParserError => e
      raise "zammad_webhooks entry '#{declared['name']}': 'custom_payload' is not valid JSON once its ticket placeholders are replaced (#{e.message})"
    end
  end

  triggers.each do |declared|
    if declared['name'].to_s.empty? || !declared['condition'].is_a?(Hash) || declared['condition'].empty?
      raise "zammad_triggers entry '#{declared['name']}': 'name' and a non-empty 'condition' hash are required"
    end
    unless webhooks.any? { |w| w['name'] == declared['webhook'] }
      raise "zammad_triggers entry '#{declared['name']}': webhook '#{declared['webhook']}' is not declared in zammad_webhooks"
    end
  end

  # --- Version guards: fail naming the attribute instead of guessing ---------
  webhook_attributes = Webhook.attribute_names
  webhooks.each do |declared|
    needed = []
    needed += %w[customized_payload custom_payload] if declared['custom_payload']
    needed += %w[bearer_token] if declared['bearer_token']
    next unless needed.any?

    missing = needed - webhook_attributes
    next unless missing.any?
    raise "zammad_webhooks entry '#{declared['name']}': this Zammad's Webhook model is missing #{missing.join(', ')} — cannot seed those attributes"
  end

  # --- Webhooks: idempotent by name; only declared fields are managed --------
  webhooks.each do |declared|
    webhook = Webhook.find_or_initialize_by(name: declared['name'])
    webhook.assign_attributes(
      endpoint: declared['endpoint'],
      ssl_verify: declared.fetch('ssl_verify', true),
      active: declared.fetch('active', true)
    )
    webhook.note = declared['note'] if declared.key?('note')
    if declared['custom_payload']
      webhook.customized_payload = true
      webhook.custom_payload = declared['custom_payload']
    end
    webhook.bearer_token = declared['bearer_token'] if declared['bearer_token']
    next unless webhook.new_record? || webhook.changed?

    webhook.save!
    changed = true
  end

  # --- Triggers: condition from variables, action built here (webhook only) --
  triggers.each do |declared|
    target = Webhook.find_by(name: declared['webhook'])
    raise "zammad_triggers entry '#{declared['name']}': webhook '#{declared['webhook']}' not found in Zammad yet" if target.nil?

    trigger = Trigger.find_or_initialize_by(name: declared['name'])
    trigger.assign_attributes(
      condition: declared['condition'],
      activator: declared.fetch('activator', 'action'),
      execution_condition_mode: declared.fetch('execution_condition_mode', 'selective'),
      active: declared.fetch('active', true),
      perform: { 'notification.webhook' => { 'webhook_id' => target.id.to_s } }
    )
    trigger.note = declared['note'] if declared.key?('note')
    next unless trigger.new_record? || trigger.changed?

    trigger.save!
    changed = true
  end
end
