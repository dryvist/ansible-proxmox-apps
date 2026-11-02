# --- Incident ticket templates (best-effort; declarative data via ENV json) --
# Prefill the ticket-create form for fast incident filing. Idempotent by name.
# group/priority are resolved by NAME here so the role YAML carries no Zammad
# ids. Optional incident custom fields (detection_method) are added ONLY when the
# attribute exists, so a template still seeds cleanly on an instance that never
# ran the opt-in zammad_seed_incidents custom-field seed.
begin
  require 'json'
  JSON.parse(ENV['ZAMMAD_TICKET_TEMPLATES'] || '[]').each do |tpl|
    grp  = Group.find_by(name: tpl['group'])
    prio = Ticket::Priority.find_by(name: tpl['priority'])
    options = {}
    options['ticket.title'] = { 'value' => tpl['title'] } if tpl['title']
    options['ticket.group_id'] = { 'value' => grp.id.to_s, 'value_completion' => grp.name } if grp
    options['ticket.priority_id'] = { 'value' => prio.id.to_s, 'value_completion' => prio.name } if prio
    if tpl['detection_method'] && ObjectManager::Attribute.get(object: 'Ticket', name: 'detection_method')
      options['ticket.detection_method'] = { 'value' => tpl['detection_method'] }
    end
    # find-or-create, reconciling options on drift so an edit to the role YAML
    # propagates. Template#options is stored verbatim, so this compare is stable
    # across converges (no churn).
    template = Template.find_by(name: tpl['name'])
    if template.nil?
      Template.create!(name: tpl['name'], active: true, options: options)
      changed = true
    elsif template.options != options
      template.update!(options: options)
      changed = true
    end
  end
rescue => e
  warn "WARN: ticket templates not seeded automatically (#{e.class}: #{e.message}). Create them once in the UI."
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
