# Idempotent Ticket custom-field seed — run via `zammad run rails r
# object_manager_attributes.rb`. Adds the incident-tracking fields used by
# zz_incidents.rb: incident_start/end, affected_services, root_cause,
# detection_method, source_issue. All optional (null: true), shown on
# create/edit/view. Guarded by ObjectManager::Attribute.get so a re-run is a
# no-op; only actually-new/changed attrs trigger migration_execute, mirroring
# zammad_bootstrap.rb's changed-flag + ZAMMAD_ATTRS_CHANGED marker pattern.

changed = false
UserInfo.current_user_id = 1

SCREENS = {
  'create' => { '-all-' => { shown: true, item_class: 'column' } },
  'edit'   => { '-all-' => { shown: true, item_class: 'column' } },
  'view'   => { '-all-' => { shown: true } },
}.freeze

def add_attribute(name, position, base_options)
  return false if ObjectManager::Attribute.get(object: 'Ticket', name: name)

  ObjectManager::Attribute.add(
    object: 'Ticket',
    name: name,
    editable: true,
    active: true,
    screens: SCREENS,
    position: position,
    **base_options,
  )
  true
end

changed = true if add_attribute('incident_start', 1500,
  display: 'Incident Start',
  data_type: 'datetime',
  data_option: { future: true, past: true, diff: 0, null: true })

changed = true if add_attribute('incident_end', 1501,
  display: 'Incident End',
  data_type: 'datetime',
  data_option: { future: true, past: true, diff: 0, null: true })

changed = true if add_attribute('affected_services', 1502,
  display: 'Affected Services',
  data_type: 'multiselect',
  data_option: {
    default: '',
    multiple: true,
    null: true,
    # Keep this list aligned with the real estate — an incident forced into
    # 'other' is an incident you cannot filter for later. Extend it rather
    # than reusing 'other' when a new service class shows up.
    options: {
      'vikunja'       => 'vikunja',
      'zammad'        => 'zammad',
      'openproject'   => 'openproject',
      'postgres'      => 'postgres',
      'postgres-apps' => 'postgres-apps',
      'traefik'       => 'traefik',
      'nautobot'      => 'nautobot',
      'hermes'        => 'hermes',
      'llm-serving'   => 'llm-serving',
      'splunk'        => 'splunk',
      'cribl'         => 'cribl',
      'network'       => 'network',
      'dns'           => 'dns',
      'proxmox'       => 'proxmox',
      'media'         => 'media',
      'other'         => 'other',
    },
  })

changed = true if add_attribute('root_cause', 1503,
  display: 'Root Cause',
  data_type: 'textarea',
  data_option: { type: 'textarea', maxlength: 8000, null: true, rows: 4 })

changed = true if add_attribute('detection_method', 1504,
  display: 'Detection Method',
  data_type: 'select',
  data_option: {
    default: '',
    null: true,
    options: {
      'probe'       => 'probe',
      'user-report' => 'user-report',
      'alert'       => 'alert',
      'agent'       => 'agent',
      'other'       => 'other',
    },
  })

changed = true if add_attribute('source_issue', 1505,
  display: 'Source Issue',
  data_type: 'input',
  data_option: { type: 'text', maxlength: 200, null: true })

ObjectManager::Attribute.migration_execute if changed

puts 'ZAMMAD_ATTRS_CHANGED' if changed
