# --- AI provider: Zammad AI on Hermes' brain (best-effort; UI fallback) -------
# Point Zammad's AI at the SAME LiteLLM router Hermes/n8n use (provider
# custom_open_ai). Seeded with validate:false so an unreachable brain at converge
# time never aborts the essential seeding above — the validated path pings
# <url>/models AND makes a live chat request (and mutates the config to add
# model_temperature_support). Order matters: ai_provider_config must be present
# BEFORE ai_provider is flipped true (Setting::Validation::AIProvider rejects
# ai_provider=true with a blank config). Gated on ZAMMAD_AI_ENABLED; a version/
# schema drift warns rather than aborting (like the KB + overviews blocks).
if ENV['ZAMMAD_AI_ENABLED'] == 'true'
  begin
    desired_ai = {
      provider: ENV['ZAMMAD_AI_PROVIDER'].to_s.empty? ? 'custom_open_ai' : ENV['ZAMMAD_AI_PROVIDER'],
      url:      env!('ZAMMAD_AI_PROVIDER_URL'),
      model:    env!('ZAMMAD_AI_MODEL'),
      token:    ENV['ZAMMAD_AI_PROVIDER_TOKEN'].to_s, # optional for custom_open_ai
    }
    # Idempotency: compare ONLY the keys we manage against the stored config, so a
    # validation-added key (e.g. model_temperature_support) can't force a
    # perpetual "changed". Stored config round-trips with string keys.
    current_ai = Setting.get('ai_provider_config') || {}
    if desired_ai.any? { |k, v| current_ai[k.to_s] != v }
      Setting.set('ai_provider_config', desired_ai, validate: false)
      changed = true
    end
    unless Setting.get('ai_provider') == true
      Setting.set('ai_provider', true, validate: false)
      changed = true
    end
    # Per-feature toggles (comma-separated list from ZAMMAD_AI_FEATURES).
    (ENV['ZAMMAD_AI_FEATURES'] || '').split(',').map(&:strip).reject(&:empty?).each do |feature|
      changed = true if set_setting(feature, true)
    end
  rescue => e
    warn "WARN: Zammad AI provider not configured automatically (#{e.class}: #{e.message}). " \
         'Configure it once in Admin > System > AI.'
  end
end

puts 'ZAMMAD_BOOTSTRAP_CHANGED' if changed
