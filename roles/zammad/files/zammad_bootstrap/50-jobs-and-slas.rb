# --- Jobs: time-based automation, defined as DATA in zammad_jobs -------------
# (role defaults, ZAMMAD_JOBS json env). Idempotent by name — mirrors
# zammad_overviews. `state` is resolved by NAME here, so the YAML carries no
# Zammad internal ids. Daily-only timeplan for now (every weekday, at the
# declared hour/minute) — a per-weekday schedule can be added here if a job
# ever needs one.
begin
  require 'json'
  JSON.parse(ENV['ZAMMAD_JOBS'] || '[]').each do |job|
    next if Job.exists?(name: job['name'])

    state = Ticket::State.find_by(name: job['state'])
    if state.nil?
      warn "WARN: state '#{job['state']}' not found — skipping job '#{job['name']}'."
      next
    end

    condition = { 'ticket.state_id' => { 'operator' => 'is', 'value' => [state.id] } }
    if job['stale_after_days']
      condition['ticket.created_at'] =
        { 'operator' => 'before (relative)', 'range' => 'day', 'value' => job['stale_after_days'] }
    end
    condition['ticket.owner_id'] = { 'operator' => 'is', 'value' => [1] } if job['unassigned']

    timeplan = {
      'days'    => %w[Mon Tue Wed Thu Fri Sat Sun].index_with { true },
      'hours'   => Array(job.dig('timeplan', 'hours')).index_with { true }.transform_keys(&:to_s),
      'minutes' => Array(job.dig('timeplan', 'minutes')).index_with { true }.transform_keys(&:to_s),
    }

    Job.create!(
      name: job['name'], active: true, timeplan: timeplan, condition: condition,
      perform: { 'ticket.tags' => { 'operator' => 'add', 'value' => job['add_tag'] } },
      disable_notification: !!job['disable_notification']
    )
    changed = true
  end
rescue => e
  warn "WARN: jobs not seeded automatically (#{e.class}: #{e.message}). Create them once in the UI."
end

# --- SLA: first-response deadline, defined as DATA in zammad_slas -----------
# (role defaults, ZAMMAD_SLAS json env). An Sla needs a Calendar, so a
# dedicated 24x7 one (ZAMMAD_SLA_CALENDAR_NAME) is seeded first, idempotently
# by name, and referenced by id. Each Sla is then seeded idempotently by name,
# with `state` resolved by NAME — same pattern as zammad_overviews/zammad_jobs.
begin
  require 'json'
  slas = JSON.parse(ENV['ZAMMAD_SLAS'] || '[]')
  if slas.any?
    calendar_name = env!('ZAMMAD_SLA_CALENDAR_NAME')
    calendar = Calendar.find_by(name: calendar_name)
    if calendar.nil?
      all_day = { 'active' => true, 'timeframes' => [['00:00', '24:00']] }
      calendar = Calendar.create!(
        name: calendar_name, timezone: 'UTC', default: false,
        business_hours: %w[mon tue wed thu fri sat sun].index_with { all_day }
      )
      changed = true
    end

    slas.each do |sla|
      next if Sla.exists?(name: sla['name'])

      state = Ticket::State.find_by(name: sla['state'])
      if state.nil?
        warn "WARN: state '#{sla['state']}' not found — skipping SLA '#{sla['name']}'."
        next
      end

      Sla.create!(
        name: sla['name'], calendar_id: calendar.id, active: true,
        condition: { 'ticket.state_id' => { 'operator' => 'is', 'value' => [state.id] } },
        response_time: sla['first_response_minutes']
      )
      changed = true
    end
  end
rescue => e
  warn "WARN: SLA/calendar not seeded automatically (#{e.class}: #{e.message}). Create them once in the UI."
end
