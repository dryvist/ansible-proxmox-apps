# Idempotent Zammad bootstrap — run via `zammad run rails r zammad_bootstrap.rb`.
# All inputs arrive as ENV so no secret appears on the command line. Numbered
# fragments share this binding and the `changed` marker across their sections.
bootstrap_fragment_dir = File.join(__dir__, 'ansible_bootstrap')
bootstrap_binding = binding
Dir[File.join(bootstrap_fragment_dir, '*.rb')].sort.each do |bootstrap_fragment|
  begin
    eval(File.read(bootstrap_fragment), bootstrap_binding, bootstrap_fragment)
  rescue StandardError, ScriptError => e
    # The task running this is no_log. Name the failure in one line: fragment,
    # line and class only, never the message, which can carry input values.
    # Re-raise so the run still fails.
    failed_frame = (e.backtrace || []).find { |frame| frame.start_with?("#{bootstrap_fragment}:") }
    failed_line = failed_frame ? failed_frame.split(':')[1] : '?'
    puts "ZAMMAD_BOOTSTRAP_FAILED fragment=#{File.basename(bootstrap_fragment)} line=#{failed_line} class=#{e.class}"
    $stdout.flush
    raise
  end
end
