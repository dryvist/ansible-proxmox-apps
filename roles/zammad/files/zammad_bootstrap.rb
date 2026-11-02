# Idempotent Zammad bootstrap — run via `zammad run rails r zammad_bootstrap.rb`.
# All inputs arrive as ENV so no secret appears on the command line. Numbered
# fragments share this binding and the `changed` marker across their sections.
bootstrap_fragment_dir = File.join(__dir__, 'ansible_bootstrap')
bootstrap_binding = binding
Dir[File.join(bootstrap_fragment_dir, '*.rb')].sort.each do |bootstrap_fragment|
  eval(File.read(bootstrap_fragment), bootstrap_binding, bootstrap_fragment)
end
