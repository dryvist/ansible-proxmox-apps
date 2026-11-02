# --- Outbound email via the Mailpit relay (best-effort; manual UI fallback) --
begin
  channel = Channel.find_by(area: 'Email::Notification')
  desired = {
    adapter: 'smtp', host: smtp_host, port: smtp_port,
    ssl: false, start_tls: false, user: '', password: ''
  }
  if channel.nil?
    Channel.create!(
      area: 'Email::Notification', group_id: Group.first&.id,
      options: { outbound: { adapter: 'smtp', options: desired } }, active: true
    )
    changed = true
  elsif channel.options.dig('outbound', 'options', 'host') != smtp_host
    channel.options = { 'outbound' => { 'adapter' => 'smtp', 'options' => desired.transform_keys(&:to_s) } }
    channel.save!
    changed = true
  end
  changed = true if set_setting('notification_sender', sender)
rescue => e
  warn "WARN: Mailpit notification channel not configured automatically (#{e.class}: #{e.message}). Configure it once in the UI."
end

# --- Knowledge base + docs-linking answers (best-effort; manual UI fallback) --
# Creates the KB if absent, then ensures a "Documentation" category whose answers
# link OUT to the docs site — the external link lives in the rich-HTML answer
# body (Zammad has no dedicated redirect field). All wrapped: KB model APIs shift
# between versions, so drift WARNS rather than aborting, and every step has a
# one-screen UI fallback. Idempotent by KB presence + category/answer title.
begin
  if defined?(KnowledgeBase)
    kb = KnowledgeBase.first
    if kb.nil?
      kb = KnowledgeBase.create!(
        iconset: 'FontAwesome', color_highlight: '#38ae6a', color_header: '#f9fafb',
        homepage_layout: 'grid', category_layout: 'grid', active: true, translations: []
      )
      changed = true
    end

    kb_locale = nil
    if kb.respond_to?(:kb_locales)
      kb_locale = kb.kb_locales.find_by(primary: true) || kb.kb_locales.first
      if kb_locale.nil?
        kb_locale = kb.kb_locales.create!(kb_locale: 'en-us', primary: true)
        changed = true
      end
    end

    require 'json'
    cat_name = ENV['ZAMMAD_KB_DOCS_CATEGORY'].to_s
    answers  = JSON.parse(ENV['ZAMMAD_KB_ANSWERS'] || '[]')
    if kb_locale && !cat_name.empty? && answers.any?
      # find-or-create the docs category, matched by its translated title
      category = kb.categories.detect { |c| c.translations.any? { |t| t.title == cat_name } }
      if category.nil?
        category = kb.categories.create!(category_icon: 'f02d')
        category.translations.create!(title: cat_name, kb_locale: kb_locale)
        changed = true
      end
      answers.each do |a|
        body = "<p>#{a['blurb']}</p>" \
               "<p><a href=\"#{a['url']}\" target=\"_blank\" rel=\"noopener\">#{a['url']}</a></p>"
        translation = KnowledgeBase::Answer::Translation.find_by(title: a['title'])
        if translation.nil?
          answer = category.answers.create!
          answer.translations.create!(
            title: a['title'], kb_locale: kb_locale,
            content: KnowledgeBase::Answer::Translation::Content.new(body: body)
          )
          answer.update!(published_at: Time.current) if answer.respond_to?(:published_at)
          changed = true
        else
          # Reconcile drift when the docs URL or blurb changes. Compare on the
          # URL + blurb TEXT, not the exact body: Zammad sanitizes answer HTML on
          # save (tag/attribute rewrites), so an exact-body compare would report
          # changed on every converge.
          stored = translation.content&.body.to_s
          unless stored.include?(a['url']) && stored.include?(a['blurb'])
            if translation.content
              translation.content.update!(body: body)
            else
              translation.update!(content: KnowledgeBase::Answer::Translation::Content.new(body: body))
            end
            changed = true
          end
        end
      end
    end
  end
rescue => e
  warn "WARN: knowledge base docs answers not seeded automatically (#{e.class}: #{e.message}). Add them once in the UI."
end
