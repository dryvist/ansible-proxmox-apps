# --- Agent webhooks: high-priority tickets start the zammad-triage agent ------
# ZAMMAD_TRIAGE_WEBHOOK_URL is the agent's webhook endpoint. When it is empty
# this section does nothing, so a converge without the value changes nothing.
# Idempotent by name: the webhook and trigger are created once and their
# endpoint, condition and payload are reconciled on every run.
begin
  require 'json'
  triage_url = ENV['ZAMMAD_TRIAGE_WEBHOOK_URL'].to_s
  unless triage_url.empty?
    # One event, one run: the key is the ticket id plus the update time, so a
    # redelivery of the same update carries the same key.
    payload = {
      'idempotency_key' => '#{ticket.id}-#{ticket.updated_at}',
      'source' => 'zammad',
      'type' => 'ticket.high_priority',
      'ticket_id' => '#{ticket.id}',
      'ticket_number' => '#{ticket.number}',
      'title' => '#{ticket.title}',
      'state' => '#{ticket.state.name}',
      'priority' => '#{ticket.priority.name}',
      'group' => '#{ticket.group.name}',
      'updated_at' => '#{ticket.updated_at}',
    }
    webhook = Webhook.find_or_initialize_by(name: 'zammad-triage agent')
    webhook.assign_attributes(
      endpoint: triage_url, ssl_verify: true, active: true,
      customized_payload: true, custom_payload: JSON.pretty_generate(payload),
      note: 'Managed by ansible-proxmox-apps roles/zammad (55-agent-webhooks.rb).'
    )
    if webhook.new_record? || webhook.changed?
      webhook.save!
      changed = true
    end

    high = Ticket::Priority.find_by(name: '3 high')
    if high.nil?
      warn "WARN: priority '3 high' not found; zammad-triage trigger not seeded."
    else
      trigger = Trigger.find_or_initialize_by(name: 'zammad-triage on high priority')
      trigger.assign_attributes(
        active: true,
        activator: 'action',
        execution_condition_mode: 'selective',
        condition: {
          'ticket.action' => { 'operator' => 'is', 'value' => %w[create update] },
          'ticket.priority_id' => { 'operator' => 'is', 'value' => [high.id.to_s] },
        },
        perform: { 'notification.webhook' => { 'webhook_id' => webhook.id.to_s } },
        note: 'Managed by ansible-proxmox-apps roles/zammad (55-agent-webhooks.rb).'
      )
      if trigger.new_record? || trigger.changed?
        trigger.save!
        changed = true
      end
    end
  end
rescue => e
  warn "WARN: zammad-triage webhook not seeded (#{e.class}: #{e.message})."
end
