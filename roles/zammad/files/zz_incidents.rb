# Zammad backdated incident seed — merges the two prior hand-run seed scripts
# (zz_seed.rb: org/groups + incident history; zz_seed2.rb: docs-migration +
# GitHub-issue narratives) into one idempotent script, and populates the new
# ObjectManager custom fields (see object_manager_attributes.rb, which MUST
# run first) on every ticket. Adds one new incident for 2026-07-17.
#
# Run via: zammad run rails r zz_incidents.rb
# Idempotent: find-or-create by title; on an existing ticket, backfills any
# custom-field values that differ (handles the case where this script's
# custom-field set grows after tickets were first seeded). Article blocks are
# skipped if the ticket already exists; add_article guards by marker subject.
UserInfo.current_user_id = 1
admin = User.find_by(email: 'admin@jacobpevans.com')
raise 'admin user not found — run zammad_bootstrap.rb first' unless admin

org = Organization.find_by(name: 'dryvist') ||
      Organization.create!(name: 'dryvist', shared: true, active: true,
                            note: 'Top-level org — homelab + AI estate')
admin.update!(organization_id: org.id) unless admin.organization_id == org.id

groups = {}
['Incidents', 'Homelab Infrastructure', 'AI/LLM Serving', 'Hermes Agent'].each do |g|
  grp = Group.find_by(name: g) || Group.create!(name: g, active: true)
  groups[g] = grp
  unless admin.group_ids_access('full').include?(grp.id)
    admin.group_names_access_map = admin.group_names_access_map.merge(grp.name => ['full'])
    admin.save!
  end
end
hi = groups['Homelab Infrastructure']
ai = groups['AI/LLM Serving']
ha = groups['Hermes Agent']

closed = Ticket::State.find_by(name: 'closed')
open_s = Ticket::State.find_by(name: 'open')
crit  = Ticket::Priority.find_by(name: '4 critical') || Ticket::Priority.find_by(id: 3)
high  = Ticket::Priority.find_by(name: '3 high')
norm  = Ticket::Priority.find_by(name: '2 normal')

def seed_ticket(title:, group:, state:, priority:, customer:, created:, closed_at: nil, articles: [], custom: {})
  t = Ticket.find_by(title: title)
  if t.nil?
    t = Ticket.create!(
      title: title, group_id: group.id, state_id: state.id, priority_id: priority.id,
      customer_id: customer.id, owner_id: customer.id,
      created_at: created, updated_at: closed_at || created,
      **custom
    )
    articles.each do |a|
      Ticket::Article.create!(ticket_id: t.id, type_id: Ticket::Article::Type.find_by(name: 'note').id,
                               sender_id: Ticket::Article::Sender.find_by(name: 'Agent').id,
                               from: 'claude-operator', subject: a[:subject], body: a[:body],
                               internal: false, content_type: 'text/plain',
                               created_at: a[:at] || created, updated_at: a[:at] || created)
    end
    t.update_columns(close_at: closed_at, updated_at: closed_at) if closed_at
    puts "created ##{t.number} #{title[0..60]}"
  else
    # Backfill custom fields on a ticket seeded before this field set existed.
    drift = custom.select { |k, v| t.public_send(k) != v }
    t.update!(drift) if drift.any?
    puts "exists ##{t.number} #{title[0..60]}#{drift.any? ? " (backfilled #{drift.keys.join(',')})" : ''}"
  end
  t
end

def add_article(ticket, subject:, body:, at:, close: nil, custom: {})
  if Ticket::Article.exists?(ticket_id: ticket.id, subject: subject)
    puts "skip article (exists): #{subject}"
    return
  end
  Ticket::Article.create!(ticket_id: ticket.id, type_id: Ticket::Article::Type.find_by(name: 'note').id,
                           sender_id: Ticket::Article::Sender.find_by(name: 'Agent').id,
                           from: 'claude-operator', subject: subject, body: body,
                           internal: false, content_type: 'text/plain', created_at: at, updated_at: at)
  ticket.update!(custom) if custom.any?
  if close
    ticket.update!(state_id: close.id)
    ticket.update_columns(close_at: at, updated_at: at)
  end
  puts "updated ##{ticket.number}: #{subject}"
end

# ============================================================================
# From zz_seed.rb (seed 1) — homelab estate-review incident history
# ============================================================================

seed_ticket(
  title: 'Zammad ITSM down — never completed first converge (T1-01)',
  group: hi, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 7, 14, 21, 0), closed_at: Time.utc(2026, 7, 16, 23, 20),
  custom: {
    incident_start: Time.utc(2026, 7, 14, 21, 0), incident_end: Time.utc(2026, 7, 16, 23, 20),
    affected_services: ['zammad'],
    root_cause: 'Role never completed a clean converge: ES path.data/path.logs restated (apps#960); ES deb auto-config transport-SSL keystore entries stripped (apps#970); dpkg --unpack deps resolved at configure (apps#973); OpenBao pre-fetch play tagged always (apps#1007); schema migrated before seed (apps#1010); hermes API token promoted + permission scopes granted.',
    detection_method: 'user-report', source_issue: 'Vikunja T1-01',
  },
  articles: [
    { subject: 'Outage', body: 'zammad.jacobpevans.com timing out; guest existed but the role had never completed a clean converge (estate review 2026-07-14, Vikunja T1-01).' },
    { subject: 'Resolution', at: Time.utc(2026, 7, 16, 23, 20), body: 'Restored 2026-07-16 across six converge iterations: ES needed path.data/path.logs restated (apps#960); ES deb auto-config transport-SSL keystore entries stripped (apps#970); dpkg --unpack deps resolved at configure (apps#973); OpenBao pre-fetch play tagged always so tagged converges stop templating empty secrets (apps#1007); schema migrated before seed (apps#1010); hermes API token promoted to ai/hermes + stored value aligned + permission scopes granted. Residual: Traefik HTTPS ingress pending tofu inventory refresh; DB auth pending postgres-apps credential reconciliation.' },
  ]
)

wedge = seed_ticket(
  title: 'vllm-mlx 0.4.0 batch-scheduler wedge — zero-token HTTP 200 completions until restart (nix-ai#1234)',
  group: ai, state: open_s, priority: crit, customer: admin,
  created: Time.utc(2026, 7, 15, 21, 0),
  custom: {
    incident_start: Time.utc(2026, 7, 15, 21, 0),
    affected_services: ['llm-serving'],
    root_cause: 'mlx_lm BatchedGenerator.extend pads processor-free batch entries with None instead of []; _step() iterates unconditionally, raising TypeError and wedging the scheduler thread whenever a penalty-free request batches with a penalized one.',
    detection_method: 'alert', source_issue: 'nix-ai#1234',
  },
  articles: [
    { subject: 'Incident', body: 'Engine wedges under concurrent load (~35 min): broadcast_shapes crash, then EVERY completion returns HTTP 200 with finish_reason=error and 0 tokens; self-recovery never clears it; ~15h of failed Hermes crons (805 errors / 603 consecutive zero-token completions). Reproduces on BOTH Qwen3.6-35B twins. Second mode observed 2026-07-16: hard hang, no crash signature. launchctl kickstart is the only remedy; kickstarts leak orphaned engine processes that hoard Metal memory and tighten recurrence.' },
    { subject: 'Mitigations shipped', at: Time.utc(2026, 7, 16, 23, 0), body: 'Watchdog validates completion bodies + completion_tokens>=1 (apps#939/#954); cron fleet calmed ~85% + staggered with hourly digest heartbeat (apps#959/#963); harmful sub-window fallback removed (apps#954); temporary probe->kickstart auto-heal loop live on the Studio. Operator constraints: stay on latest vllm-mlx, keep batching/queueing for <40B models, no downgrades; fall-forward stack evaluation (llama.cpp-Metal stand-in) on the table. Root cause OPEN in nix-ai#1234.' },
  ]
)

seed_ticket(
  title: 'Hermes memory subsystem dead — hindsight-client version pin mismatch + gateway cwd',
  group: ha, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 7, 10, 4, 6), closed_at: Time.utc(2026, 7, 17, 0, 0),
  custom: {
    incident_start: Time.utc(2026, 7, 10, 4, 6), incident_end: Time.utc(2026, 7, 17, 0, 0),
    affected_services: ['hermes'],
    root_cause: 'Gateway hindsight plugin hard-pinned hindsight-client==0.6.1 while hindsight-all resolved 0.8.4 (lazy pip-install could never succeed in the venv), and the unit WorkingDirectory was the parent of HERMES_HOME while the plugin resolves .env relative to cwd.',
    detection_method: 'agent', source_issue: 'ansible-proxmox-ai#4',
  },
  articles: [
    { subject: 'Incident', body: "Every memory tool call failed 'Memory is not available' since 2026-07-10 — Hermes ran stateless across all cron sessions. Two stacked causes: the gateway hindsight plugin hard-pins hindsight-client==0.6.1 while hindsight-all resolved 0.8.4 (lazy pip-install can never succeed in the venv), AND the unit's WorkingDirectory was the parent of HERMES_HOME while the plugin resolves .env relative to cwd." },
    { subject: 'Resolution', at: Time.utc(2026, 7, 17, 0, 0), body: 'Venv pinned to the plugin\'s client version + unit WorkingDirectory=HERMES_HOME (ansible-proxmox-ai#4 + #8), verified live: _check_local_runtime() returns (True, None).' },
  ]
)

seed_ticket(
  title: 'ai-default fallback below the primary\'s context floor poisoned every Hermes cron',
  group: ai, state: closed, priority: crit, customer: admin,
  created: Time.utc(2026, 7, 16, 14, 33), closed_at: Time.utc(2026, 7, 16, 16, 21),
  custom: {
    incident_start: Time.utc(2026, 7, 16, 14, 33), incident_end: Time.utc(2026, 7, 16, 16, 21),
    affected_services: ['llm-serving'],
    root_cause: 'The ai-default->qwen3-4b fallback (apps#939) routed 16k+ prompts to a 2048-token CPU backend on engine wedge; Hermes adopted the 2048 window, and the tiny watchdog probe fit in 2048 so the fleet never paused.',
    detection_method: 'agent', source_issue: 'apps#939',
  },
  articles: [
    { subject: 'Incident', body: "The ai-default->qwen3-4b fallback (apps#939) routed 16k+ prompts to a 2048-token CPU backend on engine wedge; Hermes adopted the 2048 window ('Context length exceeded (2,948 tokens). Cannot compress further') and every cron failed 14:33-15:39Z. The tiny watchdog probe FIT in 2048, masking the wedge — fleet never paused." },
    { subject: 'Resolution', at: Time.utc(2026, 7, 16, 16, 21), body: 'Fallback removed (fail loud) + probe requires completion_tokens>=1 (apps#954). Rule: never chain a fallback whose served context is below the primary\'s window. 16:18Z tick verified clean.' },
  ]
)

seed_ticket(
  title: 'Hermes Vikunja API token expired — agent could not write its task sink',
  group: ha, state: closed, priority: norm, customer: admin,
  created: Time.utc(2026, 7, 16, 11, 0), closed_at: Time.utc(2026, 7, 16, 20, 30),
  custom: {
    incident_start: Time.utc(2026, 7, 16, 11, 0), incident_end: Time.utc(2026, 7, 16, 20, 30),
    affected_services: %w[vikunja hermes],
    root_cause: 'VIKUNJA_API_TOKEN in secret/ai/hermes (and ai/vikunja api_token) returned 401.',
    detection_method: 'agent', source_issue: 'n/a',
  },
  articles: [
    { subject: 'Resolution', at: Time.utc(2026, 7, 16, 20, 30), body: 'VIKUNJA_API_TOKEN in secret/ai/hermes (and ai/vikunja api_token) returned 401; replaced with the working Doppler ai-ci-automation token, verified 200 against /api/v1/projects.' },
  ]
)

seed_ticket(
  title: 'Splunk skill passed app=enterprise_security — every query errored',
  group: ha, state: closed, priority: norm, customer: admin,
  created: Time.utc(2026, 7, 16, 11, 26), closed_at: Time.utc(2026, 7, 16, 21, 40),
  custom: {
    incident_start: Time.utc(2026, 7, 16, 11, 26), incident_end: Time.utc(2026, 7, 16, 21, 40),
    affected_services: %w[splunk hermes],
    root_cause: 'This Splunk instance has no app contexts; the skill passed an unsupported app parameter on every query.',
    detection_method: 'agent', source_issue: 'nix-hermes#5',
  },
  articles: [
    { subject: 'Resolution', at: Time.utc(2026, 7, 16, 21, 40), body: 'This Splunk has no app contexts; skill guardrail added: never pass an app parameter (nix-hermes#5).' },
  ]
)

seed_ticket(
  title: 'Daily brain rotation ran as a no-op flip restarting litellm twice daily',
  group: ai, state: closed, priority: norm, customer: admin,
  created: Time.utc(2026, 7, 16, 13, 0), closed_at: Time.utc(2026, 7, 16, 22, 50),
  custom: {
    incident_start: Time.utc(2026, 7, 16, 13, 0), incident_end: Time.utc(2026, 7, 16, 22, 50),
    affected_services: ['llm-serving'],
    root_cause: 'Both rotation phases had served the same model since apps#948; the rotation restarted litellm twice daily for no behavioral change.',
    detection_method: 'probe', source_issue: 'apps#964',
  },
  articles: [
    { subject: 'Resolution', at: Time.utc(2026, 7, 16, 22, 50), body: 'Both phases had served the same model since apps#948; rotation + night-cluster machinery deleted, ai-default now a static first-class alias (apps#964). Routers converged; timers removed.' },
  ]
)

seed_ticket(
  title: 'Router alerting watched an empty index — 8.9k serving errors unalerted',
  group: ai, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 7, 16, 9, 0), closed_at: Time.utc(2026, 7, 16, 13, 30),
  custom: {
    incident_start: Time.utc(2026, 7, 16, 9, 0), incident_end: Time.utc(2026, 7, 16, 13, 30),
    affected_services: ['llm-serving'],
    root_cause: 'Both LLM-router Splunk alerts watched index=ai sourcetype=litellm, which had zero events, so 8.9k serving errors went unalerted.',
    detection_method: 'alert', source_issue: 'ansible-splunk#342',
  },
  articles: [
    { subject: 'Resolution', at: Time.utc(2026, 7, 16, 13, 30), body: 'Both LLM-router Splunk alerts watched index=ai sourcetype=litellm (zero events ever). Repointed to index=llm host=llm-router-* with the wedge signature; all Splunk alerts now deliver via ntfy + Slack, email removed (ansible-splunk#342). Deploy pending splunk-01 SSH access.' },
  ]
)

seed_ticket(
  title: '80B swap-brain Metal OOM under concurrent cron fleet — 283x500 storm',
  group: ai, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 7, 14, 12, 0), closed_at: Time.utc(2026, 7, 15, 12, 0),
  custom: {
    incident_start: Time.utc(2026, 7, 14, 12, 0), incident_end: Time.utc(2026, 7, 15, 12, 0),
    affected_services: ['llm-serving'],
    root_cause: 'Qwen3-Next-80B exceeded its Metal resource ceiling under the concurrent cron fleet.',
    detection_method: 'alert', source_issue: 'apps#913',
  },
  articles: [
    { subject: 'Resolution', body: 'Qwen3-Next-80B exceeded its Metal resource ceiling under the concurrent fleet; 35B restored to the hot path, 80B reachable only via ai-deep-analysis (concurrency 1) — apps#913/#915.' },
  ]
)

seed_ticket(
  title: 'LLM gate hard-depended on Doppler — Hermes fully down (T1-04)',
  group: ai, state: closed, priority: crit, customer: admin,
  created: Time.utc(2026, 7, 13, 12, 0), closed_at: Time.utc(2026, 7, 16, 11, 44),
  custom: {
    incident_start: Time.utc(2026, 7, 13, 12, 0), incident_end: Time.utc(2026, 7, 16, 11, 44),
    affected_services: ['llm-serving'],
    root_cause: 'The LLM gate hard-required Doppler to be reachable at boot, so Hermes went fully down when Doppler was unavailable.',
    detection_method: 'user-report', source_issue: 'Vikunja T1-04',
  },
  articles: [
    { subject: 'Resolution', body: 'OpenBao-run shim (nix-darwin#1698) merged + Studio darwin-rebuilt; gate no longer Doppler-dependent. Verified live 2026-07-16 (Vikunja T1-04 closed).' },
  ]
)

zdb = seed_ticket(
  title: 'Zammad cannot reach its database — db missing on the host the guest targets',
  group: hi, state: open_s, priority: high, customer: admin,
  created: Time.utc(2026, 7, 16, 23, 33),
  custom: {
    incident_start: Time.utc(2026, 7, 16, 23, 33),
    affected_services: %w[zammad postgres],
    root_cause: 'The postgres host\'s zammad role password was reconciled from OpenBao apps/zammad v3 at a different time than the guest\'s database.yml re-template, causing a password desync — initially misdiagnosed as a missing database because Rails\' create-database fallback error masked the real auth failure.',
    detection_method: 'user-report', source_issue: 'apps#1005',
  },
  articles: [
    { subject: 'Incident', body: "Zammad web 500s; the guest cannot reach its database. Initially read as a password desync from the postgres-apps bring-up (apps#1005 lane), but a converge on 2026-07-17 00:51Z showed otherwise: `zammad run rake db:migrate` fails trying to CREATE the database, connecting to the `postgres` maintenance DB, which pg_hba rejects — 'no pg_hba.conf entry for host 10.0.60.54, user zammad, database postgres'. So the zammad database does not exist on postgres.jacobpevans.com, which is where the guest points (POSTGRES_PRIMARY_HOST is unset, so group_vars/all falls back to 'postgres' while the postgres-apps migration is in flight). NETWORK_CIDR_APPS (10.0.60.0/24) does cover the guest — pg_hba entries are per-database and only the zammad database is granted from that CIDR, so the maintenance-DB connection is correctly refused." },
    { subject: 'Next action', body: "Postgres lane: either converge --tags postgres so postgres_managed_databases creates the zammad db+role on postgres.jacobpevans.com, or set POSTGRES_PRIMARY_HOST to postgres-apps if pointing apps at the new host is the intended cutover. Deliberately not converged from the Zammad lane: it is another lane's host mid-migration. Once the guest reaches its database, re-run the retroactive seed and close this." },
  ]
)

# ============================================================================
# From zz_seed2.rb (seed 2) — docs-migration + GitHub-issue incident narratives
# ============================================================================

seed_ticket(
  title: 'Plex discovery outage after pve1->pve2 migration - unclaimed + unpublished (June 2026)',
  group: hi, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 6, 12, 12, 0), closed_at: Time.utc(2026, 6, 14, 1, 0),
  custom: {
    incident_start: Time.utc(2026, 6, 12, 12, 0), incident_end: Time.utc(2026, 6, 14, 1, 0),
    affected_services: %w[media proxmox],
    root_cause: "Two independent silent gaps: (1) the plex role's claim.yml is deliberately non-fatal so the converge skipped claiming, leaving the server invisible to plex.tv discovery; (2) PublishServerOnPlexOnlineKey was never reconciled, hiding the server from the account list even once claimed.",
    detection_method: 'user-report', source_issue: 'apps#427',
  },
  articles: [
    { subject: 'Incident', body: "After the media stack moved pve1->pve2 (new 7-digit VMIDs, DHCP), Plex (vmid 703040, media-svc VLAN 55) became undiscoverable from the Roku (primary client). Container healthy, correctly addressed, IaC had NO drift - the failure was runtime onboarding state the migration never completed, and it surfaced no error. A second Plex Home profile on the same TV stayed 'unavailable' even after the primary fix." },
    { subject: 'Root cause', body: "Two independent silent gaps, both required: (1) UNCLAIMED - the plex role's claim.yml is deliberately non-fatal (plex.tv claim tokens expire ~4 min, SOPS-stored tokens usually stale), so the converge skipped claiming; a Roku discovers servers through the plex.tv account, and an unclaimed server is invisible to it. (2) UNPUBLISHED - PublishServerOnPlexOnlineKey=0 hides a server from the account list; the role set libraries + customConnections but never reconciled the publish pref. Ruled out: IaC drift (deployment.json, DHCP reservation, A record all agreed), stale DNS, firewall (Internal->Internal Allow All)." },
    { subject: 'Resolution', at: Time.utc(2026, 6, 14, 1, 0), body: "Live: claimed via direct API (pct exec 703040 -- curl -XPOST localhost:32400/myplex/claim?token=..., using the server's own machineIdentifier as client id), then set PublishServerOnPlexOnlineKey=1 via /:/prefs -> presence=True, Roku discovered it. Codified: apps#427 adds publish.yml (reconciles the publish pref, default on) + loud status.yml (warns/hard-fails via plex_require_onboarded when not claimed+published). Claim stays non-fatal by design. Deferred: second-profile sharing is keyed to the OLD server's machineIdentifier (random per-install GUID - a rebuilt server is a new server to clients). Deeper lesson -> JAC-147 config-as-code program (accept-fresh identity, declarative sharing, devopsarr/Configarr, on-demand tofu plan drift detection). Gotchas: claimed alone is not discoverable without publish=1; native deb stores state under /var/lib/plexmediaserver, runs as plex uid 999." },
  ]
)

seed_ticket(
  title: 'Wi-Fi 2.4GHz airtime saturation + WAN flap storm - two failures misread (June 2026)',
  group: hi, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 6, 8, 23, 14), closed_at: Time.utc(2026, 6, 10, 12, 0),
  custom: {
    incident_start: Time.utc(2026, 6, 8, 23, 14), incident_end: Time.utc(2026, 6, 10, 12, 0),
    affected_services: ['network'],
    root_cause: "A hair-trigger custom WAN SLA flapped on a single lost ping while the ISP line was healthy, and the primary 2.4GHz-only SSID co-channel-saturated at ~96% airtime with a co-located eero on the same channel.",
    detection_method: 'user-report', source_issue: 'n/a',
  },
  articles: [
    { subject: 'Incident', body: "One evening (~7:14-8:44 PM EDT) the network failed two ways at once: Comcast appeared to disconnect repeatedly (~14 WAN failover/restore events), and a Roku 3 ft from a U7 Pro XGS streamed at <1 Mbps. Whole-home brownouts on each failover. Both symptoms were misread at first." },
    { subject: 'Root cause', body: "(1) WAN: a hair-trigger custom 'Comcast Quality' SLA (ICMP loss 3%/latency 150ms/jitter 30ms, threshold_policy any, 6 probes) trips on a single lost ping. Independent cloud ISP-metrics (api.ui.com/ea/isp-metrics) showed 0% loss and steady 18-22ms throughout - the line was healthy, the monitor was the problem. (2) Wi-Fi: the Roku sat at -35 dBm (excellent) but on 2.4GHz ch 11 at ~96% airtime, shared with ~25 clients plus a co-located eero broadcasting -22 dBm on the SAME channel; the primary 'UniFi' SSID was 2.4GHz-only, pinning dual-band clients. Throughput != signal. Ruled out: physical coax fault (no evidence - early hypothesis was wrong), weak signal, the Starlink hidden SSID (~3% airtime, negligible)." },
    { subject: 'Resolution', at: Time.utc(2026, 6, 10, 12, 0), body: "Live: WAN -> Auto SLA (flapping stopped immediately, clean 14+ h), deleted the custom SLA, added 5GHz to the primary SSID, pulled the eero off ch 11, Starlink replugged in bypass (CGNAT, no double-NAT). Roku moved to 5GHz ch 149/80MHz at 866 Mbps, stable 13+ h. CAUTION: all manual controller changes on surfaces the Terraform provider does not model (AP RF, band steering, WAN SLA) - they drift back; a UAP-AC-HD was later found stranded on the eero's new channel at 96% airtime, same failure relocated. Deeper lesson -> the Wi-Fi/WAN maintainability decision: declarative SSID+PPSK segmentation, intent-as-code with drift detection for non-declarable surfaces, finish the eero exit. Gotchas: a failover event proves the monitor tripped, not that the line degraded (confirm with cloud ISP-metrics first); check airtime not dBm; two Wi-Fi systems co-channel = self-inflicted interference; networkconf.wan_load_balance_type can misreport WAN mode." },
  ]
)

seed_ticket(
  title: 'RC11: vllm-mlx worker Jetsam-killed - 32GB cache reservation + infinite TTL',
  group: ai, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 5, 9, 12, 0), closed_at: Time.utc(2026, 5, 13, 17, 44),
  custom: {
    incident_start: Time.utc(2026, 5, 9, 12, 0), incident_end: Time.utc(2026, 5, 13, 17, 44),
    affected_services: ['llm-serving'],
    root_cause: '--cache-memory-mb 32768 (32GB reservation per worker) + the default-aliased model at ttl=0 (infinite, never unloads) built wired-pool pressure monotonically until macOS Jetsam killed the process.',
    detection_method: 'alert', source_issue: 'nix-ai#764',
  },
  articles: [
    { subject: 'Incident', body: 'MacBook LLM worker killed by macOS Jetsam. Mechanism: --cache-memory-mb 32768 (32GB reservation per worker) + the default-aliased model at ttl=0 (infinite, never unloads) -> wired-pool pressure built monotonically until macOS killed the process. Fingerprint: JetsamEvent log entry naming the vllm-mlx process. Family: one of five incidents in five weeks sharing the same root mechanism - the kernel cannot drain compressor+swap because idle-sleep is structurally blocked (recorder audio assertions).' },
    { subject: 'Resolution', at: Time.utc(2026, 5, 13, 17, 44), body: 'nix-ai#764 (merged 2026-05-13): --cache-memory-mb 32768 -> 8192, ttl 0 -> 3600. Confirmed live 2026-05-19, re-verified 2026-06-02 with no recurrence.' },
  ]
)

seed_ticket(
  title: 'RC14: overnight compressor/swap compound - 15-min sign-in sluggishness',
  group: ai, state: open_s, priority: norm, customer: admin,
  created: Time.utc(2026, 5, 19, 13, 0),
  custom: {
    incident_start: Time.utc(2026, 5, 19, 13, 0),
    affected_services: ['llm-serving'],
    root_cause: 'Multi-day uptime + recorder-blocked idle-sleep + a loaded LLM weight pool expanded dynamic swap 4GB->53GB overnight while the compressor accumulated 71GB, paying decompression latency at every sign-in action.',
    detection_method: 'alert', source_issue: 'n/a',
  },
  articles: [
    { subject: 'Incident', body: 'Mechanism: multi-day uptime (5d) + recorder running (audio assertions block idle-sleep) + LLM weight pool loaded -> macOS expanded dynamic swap 4GB->53GB overnight while the compressor accumulated 71GB of compressed pages. At sign-in every action paid decompression latency: 75% WindowServer CPU spike, ~15 min sluggishness. Fingerprint: load avg 9+ (5/15-min), swap >95% of dynamic pool, compressor >50GB, BuiltInMicrophoneDevice assertion uptime spanning the night.' },
    { subject: 'Status', body: 'OPEN: depends on a recorder-side fix to release audio assertions on display sleep (recorder RC10 in the nix-mac-performance operational repo).' },
  ]
)

seed_ticket(
  title: 'RC14 variant: stuck worker past TTL - llama-swap WaitGroup reuse race',
  group: ai, state: open_s, priority: norm, customer: admin,
  created: Time.utc(2026, 6, 2, 12, 0),
  custom: {
    incident_start: Time.utc(2026, 6, 2, 12, 0),
    affected_services: ['llm-serving'],
    root_cause: "llama-swap's per-worker lifecycle goroutine panics on unload ('WaitGroup is reused before previous Wait has returned'); the goroutine dies but the main process survives, so TTL accounting drifts and the worker never unloads.",
    detection_method: 'alert', source_issue: 'nix-ai#801',
  },
  articles: [
    { subject: 'Incident', body: "A single worker stayed resident past its 3600s TTL because llama-swap's per-worker lifecycle goroutine crashed on unload: 'panic: sync: WaitGroup is reused before previous Wait has returned' (proxy/process.go:289) - the goroutine panics, the main llama-swap process survives, TTL accounting drifts, worker never unloads. One 71GB worker resident on a 128GB host = 55% single-process RSS = same compressor/swap saturation as RC14 WITHOUT the audio-blocked-sleep prerequisite. Trigger: an internal client plugin driving the router via the OpenAI JS SDK. Fingerprint: vllm-mlx serve elapsed > 2x configured ttl; WaitGroup panic count >= 4 in vllm-mlx.error.log. Tracked as nix-ai#801." },
    { subject: 'Status', body: 'OPEN upstream: mostlygeek/llama-swap lifecycle race. Homelab-side the exposure is reduced by the serving-host posture (idleTtl 0 residents on the Studio; the race needs TTL unload cycles).' },
    { subject: 'Captured panic stack (in the wild)', body: "panic: sync: WaitGroup is reused before previous Wait has returned\n\ngoroutine 1593 [running]:\nsync.(*WaitGroup).Wait(0x14000529f30)\n  sync/waitgroup.go:208 +0x14c\ngithub.com/mostlygeek/llama-swap/proxy.(*Process).start.func1()\n  github.com/mostlygeek/llama-swap/proxy/process.go:289 +0xa4\ncreated by github.com/mostlygeek/llama-swap/proxy.(*Process).start\n  in goroutine 1491\n  github.com/mostlygeek/llama-swap/proxy/process.go:280 +0x95c\n\n(runs=1 over 4 days uptime confirmed the main process survives the goroutine panic.)" },
  ]
)

seed_ticket(
  title: 'RC15: transcription backlog - UNIQUE violation aborted reconciliation loop',
  group: ai, state: closed, priority: norm, customer: admin,
  created: Time.utc(2026, 5, 26, 12, 0), closed_at: Time.utc(2026, 6, 2, 12, 0),
  custom: {
    incident_start: Time.utc(2026, 5, 26, 12, 0), incident_end: Time.utc(2026, 6, 2, 12, 0),
    affected_services: ['media'],
    root_cause: "The recorder's transcription reconciliation worker aborted on a UNIQUE-constraint violation on the audio-transcripts table, leaving ~63,000 chunks unprocessed against the 90-day retention boundary.",
    detection_method: 'alert', source_issue: 'n/a',
  },
  articles: [
    { subject: 'Incident', body: "Not the LLM stack per se: the recorder's transcription reconciliation worker (hits the local stack via Whisper/Parakeet) aborted on a UNIQUE-constraint violation on the audio-transcripts table, leaving ~63,000 untranscribed chunks accumulating against the 90-day retention boundary (data-loss countdown)." },
    { subject: 'Resolution', at: Time.utc(2026, 6, 2, 12, 0), body: 'Structural fix in recorder v2.4.250: INSERT OR IGNORE + transcription_attempts < 5 cap. Verified 2026-06-02: 0 violations, 0 aborts; legacy backlog (10,152 chunks) draining at 628/hr.' },
  ]
)

seed_ticket(
  title: 'UDW blackholed all WireGuard handshake replies for the downloader VPN (2026-07-07)',
  group: hi, state: open_s, priority: high, customer: admin,
  created: Time.utc(2026, 7, 8, 1, 20),
  custom: {
    incident_start: Time.utc(2026, 7, 8, 1, 20),
    affected_services: %w[network media],
    root_cause: 'UDW Threat Management (Suricata IPS, prevention mode) false-positive-matched the high-entropy WireGuard flow once, caching the block in destination-keyed state that a source-IP suppression whitelist does not purge and only a restart clears.',
    detection_method: 'user-report', source_issue: 'apps#763',
  },
  articles: [
    { subject: 'Incident', body: "The downloader VPN tunnel stopped receiving handshake replies from BOTH Proton endpoints (2026-07-07 ~21:20 -> ~02:05 EDT). Outbound initiations kept leaving the Proxmox host uplink (tcpdump: packets egress, zero replies). Sticky failover fired, got one green cycle, then the backup died the same way. Fail-closed held - no leak. A UDW restart (~02:05) restored the tunnel on the existing, unchanged configs: the fault lived in GATEWAY STATE, not the tunnel configs." },
    { subject: 'Misdiagnosis to prevent', body: "A 'clean-room' WireGuard interface on a different host leg with a different source IP ALSO got zero replies, which was read as provider-side revocation. It was not - that test transited the SAME UDW. Lesson: a clean-room test is only clean if it bypasses every shared middlebox; 'both paths fail' implicates the shared element, not the endpoints." },
    { subject: 'Prime hypothesis + status', body: "UDW Threat Management (Suricata IPS, prevention mode): signature 2034805 (ET EXPLOIT Apache log4j RCE, UDP outbound) false-positive-matched the high-entropy WireGuard flow once, and the block was cached in a destination-keyed structure that a source-IP suppression whitelist does not purge and only a restart clears - explaining both-endpoints-dead, the clean-room failure, and instant recovery on restart. Secondary hypotheses: conntrack/NAT state corruption pinning :51820/udp; an in-line NFQUEUE wedge. OPEN: RCA + detection + suppression-shape deliverables tracked as engineering work in apps#763." },
  ]
)

seed_ticket(
  title: "Serving host dark ~1.5h - orphaned worker held engine port, proxy 429'd everything",
  group: ai, state: closed, priority: crit, customer: admin,
  created: Time.utc(2026, 7, 17, 0, 5), closed_at: Time.utc(2026, 7, 17, 1, 45),
  custom: {
    incident_start: Time.utc(2026, 7, 17, 0, 5), incident_end: Time.utc(2026, 7, 17, 1, 45),
    affected_services: ['llm-serving'],
    root_cause: 'launchctl kickstart against a wedged engine killed the proxy but left the detached engine holding its port; every replacement worker died binding, and neither launchd nor the models-probe watchdog noticed because /v1/models kept answering 200.',
    detection_method: 'agent', source_issue: 'nix-ai#1260',
  },
  articles: [
    { subject: 'Incident', body: "Every completion through llama-swap returned 429 for ~1.5h with zero alerts. Root cause: llama-swap spawns vllm-mlx workers through uv tool uvx DETACHED (a live worker's top process reports PPID 1), so launchctl kickstart -k - the sanctioned wedge break-fix - kills the proxy but leaves the engine holding its port (AbandonProcessGroup=false cannot reach a detached grandchild). Every replacement worker died on bind ([Errno 48] address already in use), KeepAlive restart-looped, and /v1/models kept answering 200 so neither launchd nor the models-probe watchdog noticed. THE REMEDY CAUSED THE OUTAGE: each kickstart against a wedged engine could leak an orphan - explaining the earlier observation that kickstarts 'leak engine processes and tighten recurrence'. The temporary auto-heal loop (which kickstarted) was the trigger of this instance." },
    { subject: 'Resolution', at: Time.utc(2026, 7, 17, 1, 45), body: "Immediate: killed the orphan (needed SIGKILL - a wedged engine ignores SIGTERM), port freed, serving resumed instantly. Durable (nix-ai#1260, deployed via nix-darwin#1730 + darwin-rebuild 2026-07-17 01:42Z): llama-swap-launch reaps leftover workers before the proxy starts (safe because llama-swap is the only spawner and the check is TIMING-based, not ancestry - PPID cannot discriminate since healthy workers also report PPID 1), making boot/KeepAlive/kickstart all self-cleaning; the watchdog now probes a REAL completion asserting completion_tokens >= 1 instead of /v1/models (blind through all three observed not-serving modes). Gotcha codified: Darwin's nixpkgs procps ships no pgrep/pkill - call /usr/bin paths in nix-managed scripts. Temporary /tmp auto-heal deleted after deployment." },
  ]
)

# --- Amendments carried over from seed 2 (close out earlier open tickets) ---

if wedge
  add_article(wedge,
    subject: 'Root cause found and confirmed in source',
    at: Time.utc(2026, 7, 17, 0, 40),
    body: "The wedge was never load flakiness or a version problem. vllm-mlx builds a request's logits_processors from its repetition_penalty (scheduler.py ~2046); a penalty-free request gets []. mlx_lm's BatchedGenerator.extend (generate.py ~1064) pads processor-free entries with None instead of [], and _step() (~1346) iterates the entry unconditionally -> TypeError: 'NoneType' object is not iterable -> the scheduler thread dies -> every completion on that worker hangs or returns empty until the worker is killed. ONE penalized request beside ONE penalty-free request in the same batch is fatal. Observed 26,916 times in the serving-host log - the dominant failure mode. Our traffic hit it precisely: the router injected repetition_penalty 1.05 on the ai-default alias while health probes sent bare requests, and continuous batching co-scheduled them - THE MONITORING WAS A TRIGGER. Confirmation: after making the probe carry the same penalty, the crash count froze at 26,916 (zero new) while serving continued."
  )
  add_article(wedge,
    subject: 'Resolution deployed - uniform batches by construction',
    at: Time.utc(2026, 7, 17, 1, 45),
    close: closed,
    custom: { incident_end: Time.utc(2026, 7, 17, 1, 45) },
    body: "Fix: vllm-mlx's --default-repetition-penalty applied SERVER-SIDE (programs.mlx.defaultRepetitionPenalty=1.05, nix-ai#1262), so every request gets a logits processor regardless of caller and a mixed batch is unreachable by construction (server.py:272 resolves the default when a request omits one). Deployed with nix-ai#1260 (orphan reap + real-completion watchdog) in one rebuild via nix-darwin#1730 - deliberately together, because #1260's bare completion probe would itself have been a new trigger without #1262. Verified live: all 5 models' generated commands and the running worker carry the flag; a request sent WITHOUT a penalty reached the scheduler as penalty=1.05; recent router traffic 17/17 HTTP 200. Constraints honored: latest engine only, batching stays on, no downgrade (0.3.0/0.2.9 only ever looked better when traffic happened to be uniform). Rule for the future: any health probe must send the same sampling params as production traffic. Engineering references: nix-ai#1234 (upstream bug tracking), #1260, #1262, nix-darwin#1730."
  )
else
  puts 'WARN: wedge ticket not found'
end

if zdb
  add_article(zdb,
    subject: 'Corrected diagnosis and resolution',
    at: Time.utc(2026, 7, 17, 2, 30),
    close: closed,
    custom: {
      incident_end: Time.utc(2026, 7, 17, 2, 30),
      root_cause: "It WAS a password desync (the original 23:33Z read was correct). It was mis-corrected to 'database missing' because rake db:migrate's create-database fallback error masked the real 'password authentication failed for user zammad' auth failure. The postgres host's zammad role password was set during the lane's bring-up BEFORE OpenBao apps/zammad v3 (19:43Z) and never re-reconciled, while the guest's database.yml re-templates from current bao on every converge.",
    },
    body: "Final diagnosis - it WAS a password desync, and the diagnostic journey is the lesson. The original 23:33Z read (password mismatch after the postgres re-provision) was CORRECT. It was then mis-corrected to 'database missing' because rake db:migrate surfaced only 'no pg_hba.conf entry for host ..., database postgres': when the target-db connection fails, Rails falls back to CREATING the database via the postgres maintenance DB, and THAT (correctly refused - pg_hba grants are per-database) is the only error printed, masking the real one. A raw PG.connect from the guest with the app's own database.yml creds exposed the truth: 'password authentication failed for user zammad' - db present, pg_hba entry present (host zammad zammad 10.0.60.0/24 scram-sha-256), password stale. Root cause of the desync: the postgres host's zammad role password was set during the lane's bring-up BEFORE OpenBao apps/zammad v3 (19:43Z) and never re-reconciled, while the guest's database.yml re-templates from current bao on every converge - two writes from one SSOT at different times. Fix: surgically reset the role password to the bao value (the postgres role's own postgresql_user task reconciles on converge; a full role converge was avoided to not step on the active postgres lane). Verified CONNECT OK, then a clean zammad converge (migrate+seed+bootstrap) and API 200. Lessons: (1) Rails 'Couldn't create database' means the TARGET-db connection failed for ANY reason - always test the real connection with the app's own creds before trusting the fallback error; (2) a --check postgres run fails misleadingly on cluster-config (psql --version is a command task check mode skips) - artifact, not breakage."
  )
else
  puts 'WARN: zammad db ticket not found'
end

# ============================================================================
# Today's incident (2026-07-17) — apps-tier outage
# ============================================================================

seed_ticket(
  title: 'Apps tier outage — vikunja/zammad/openproject down after RAM+disk exhaustion (2026-07-17)',
  group: hi, state: open_s, priority: crit, customer: admin,
  created: Time.utc(2026, 7, 17, 9, 0),
  custom: {
    incident_start: Time.utc(2026, 7, 17, 9, 0),
    affected_services: %w[vikunja zammad openproject postgres-apps],
    root_cause: 'Host RAM + disk exhaustion; postgres-apps DB recovered (5432 reopened) but the vikunja/zammad/openproject app services did not auto-restart. Firewall PR dryvist/tofu-proxmox#646 was already applied (repo at #683), so it was NOT the firewall this time.',
    detection_method: 'probe', source_issue: 'dryvist/nix-mac-performance#38',
  },
  articles: [
    { subject: 'Incident', body: 'Host RAM + disk exhaustion took down the apps tier: vikunja and openproject stopped answering (20s timeouts) and zammad returned 502, each on its own guest. The shared postgres-apps backend recovered on its own (port 5432 reopened, verified by probe) but the three app services did not auto-restart, so the outage outlived its cause. Ruled out this time: the firewall — dryvist/tofu-proxmox#646 ("add outbound_https rule to vikunja firewall") was already applied, with the repo at #683 and applies since, so the 2026-07-14 root cause does not apply here. Traefik itself was healthy throughout (llm.pve returned 200; ingress answered 404 on an unmatched route). Tracked in dryvist/nix-mac-performance#38.' },
  ]
)

# ============================================================================
# Today's incident (2026-07-17) — Default LAN (10.0.1.x) deleted then restored
# ============================================================================

seed_ticket(
  title: 'Default LAN 10.0.1.x (UniFi lan_main / VLAN 0) deleted then restored — self-inflicted (2026-07-17)',
  group: hi, state: closed, priority: high, customer: admin,
  created: Time.utc(2026, 7, 17, 12, 0), closed_at: Time.utc(2026, 7, 17, 13, 0),
  custom: {
    incident_start: Time.utc(2026, 7, 17, 12, 0),
    incident_end: Time.utc(2026, 7, 17, 13, 0),
    affected_services: ['network'],
    root_cause: 'After standing up a dedicated Management VLAN (UniFi lan_mgmt, VLAN 5, 10.0.5.x) alongside the original management range, the operator manually deleted the 10.0.1.x Default network (UniFi lan_main, VLAN 0) in the UniFi UI because the now-redundant range was "bothering me". 10.0.1.1 is that network gateway, so removing it dropped the default LAN. Restored manually in the UniFi UI.',
    detection_method: 'user-report', source_issue: 'dryvist/tofu-unifi (lan_main / Default network)',
  },
  articles: [
    { subject: 'Incident', body: 'The operator, having added a dedicated Management VLAN (VLAN 5, 10.0.5.x), deleted the original 10.0.1.x Default LAN (UniFi lan_main, VLAN 0) directly in the UniFi UI, judging the two overlapping management ranges redundant. That network carries the 10.0.1.1 gateway, so its removal dropped the default LAN. The mistake was recognised and the network was restored in the UniFi UI (10.0.1.1 back: pings ~2.7ms, http 301 -> https 200). Incident window is approximate (~1h, 2026-07-17 midday).' },
    { subject: 'Follow-up (IaC drift)', body: 'lan_main is a tofu-managed resource (module.networks.unifi_network.this["lan_main"], from deployment/networks.json). It was never removed from code, so DESIRED state is correct — but the manual delete+restore diverged tofu STATE: the tracked network ID is stale and the restored network is an untracked new object. A future tofu-unifi plan/apply (or the periodic drift workflow) may try to RECREATE the Default LAN, re-running the outage automatically. Resolution: run a plan; if it wants to recreate lan_main, terraform state rm the stale entry and import the restored network ID so tofu re-adopts it. Runbook staged 2026-07-17.' },
  ]
)

puts 'SEED_DONE'
