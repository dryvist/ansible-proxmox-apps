CREATE SCHEMA IF NOT EXISTS alert_delivery;
CREATE TABLE IF NOT EXISTS alert_delivery.cursor (topic text PRIMARY KEY, seen bigint NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alert_delivery.message (
 topic text NOT NULL, id text NOT NULL, happened bigint NOT NULL, body jsonb NOT NULL,
 PRIMARY KEY(topic,id)
);
CREATE TABLE IF NOT EXISTS alert_delivery.incident (
 key text PRIMARY KEY, source text NOT NULL, rule text NOT NULL, entity text NOT NULL,
 title text NOT NULL, impact text NOT NULL, active boolean NOT NULL DEFAULT true,
 details_url text, severity text NOT NULL DEFAULT 'unknown', last_general_events bigint NOT NULL DEFAULT 0, events bigint NOT NULL DEFAULT 0,
 last_seen timestamptz NOT NULL DEFAULT now(), last_general timestamptz,
 last_critical timestamptz, critical boolean NOT NULL DEFAULT false,
 ticket_id bigint, hypotheses text
);
CREATE TABLE IF NOT EXISTS alert_delivery.notification (
 id bigserial PRIMARY KEY, incident_key text REFERENCES alert_delivery.incident(key),
 channel text NOT NULL CHECK(channel IN ('general','critical')), kind text NOT NULL,
 body text NOT NULL, available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, attempts integer NOT NULL DEFAULT 0,
 acknowledged_at timestamptz, cancelled_at timestamptz, slack_ts text, delivery_key text NOT NULL UNIQUE,
 uncertain boolean NOT NULL DEFAULT false, grouped boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS alert_delivery.ticket (
 id bigserial PRIMARY KEY, incident_key text NOT NULL REFERENCES alert_delivery.incident(key),
 operation_key text NOT NULL UNIQUE, body text NOT NULL,
 available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
 attempts integer NOT NULL DEFAULT 0, acknowledged_at timestamptz
);
CREATE TABLE IF NOT EXISTS alert_delivery.enrichment (
 incident_key text PRIMARY KEY REFERENCES alert_delivery.incident(key),
 available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
 attempts integer NOT NULL DEFAULT 0, acknowledged_at timestamptz
);
CREATE TABLE IF NOT EXISTS alert_delivery.budget (
 channel text PRIMARY KEY, window_started timestamptz NOT NULL, used integer NOT NULL
);
-- Additive upgrades must run before functions reference newly introduced columns.
ALTER TABLE alert_delivery.incident ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
ALTER TABLE alert_delivery.incident ADD COLUMN IF NOT EXISTS details_url text;
ALTER TABLE alert_delivery.incident ADD COLUMN IF NOT EXISTS severity text NOT NULL DEFAULT 'unknown';
ALTER TABLE alert_delivery.incident ADD COLUMN IF NOT EXISTS last_general_events bigint NOT NULL DEFAULT 0;
ALTER TABLE alert_delivery.notification ADD COLUMN IF NOT EXISTS cancelled_at timestamptz;
ALTER TABLE alert_delivery.notification ADD COLUMN IF NOT EXISTS uncertain boolean NOT NULL DEFAULT false;
ALTER TABLE alert_delivery.notification ADD COLUMN IF NOT EXISTS grouped boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS alert_delivery.quarantine (
 fingerprint text PRIMARY KEY, sample text NOT NULL, error_code text NOT NULL,
 first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
 occurrences bigint NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS message_happened_idx ON alert_delivery.message(happened);
CREATE INDEX IF NOT EXISTS notification_ready_idx ON alert_delivery.notification(channel,available_at,id)
 WHERE acknowledged_at IS NULL AND cancelled_at IS NULL;
CREATE INDEX IF NOT EXISTS ticket_incident_pending_idx ON alert_delivery.ticket(incident_key,id)
 WHERE acknowledged_at IS NULL;
CREATE OR REPLACE FUNCTION alert_delivery.ingest(lines text, allowed_impacts text[], allowed_rules text[])
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE line text; e jsonb; p jsonb; k text; src text; rule_name text; entity_name text;
 imp text; sev text; safe_title text; urgent boolean; firing boolean; detail text; previous alert_delivery.incident%ROWTYPE; inserted integer; total integer := 0;
BEGIN
 FOREACH line IN ARRAY string_to_array(lines,E'\n') LOOP
  IF btrim(line) = '' THEN CONTINUE; END IF;
  BEGIN
  e := line::jsonb;
  IF e->>'event' IS DISTINCT FROM 'message' THEN CONTINUE; END IF;
  IF coalesce(e->>'topic','') = '' OR coalesce(e->>'id','') = '' OR e->>'time' IS NULL THEN
   RAISE EXCEPTION 'ntfy message requires topic, id and time' USING ERRCODE='22023';
  END IF;
  INSERT INTO alert_delivery.message VALUES(e->>'topic',e->>'id',(e->>'time')::bigint,e)
   ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  IF inserted = 0 THEN CONTINUE; END IF;
  BEGIN p := (e->>'message')::jsonb; EXCEPTION WHEN invalid_text_representation THEN p := '{}'::jsonb; END;
  -- Native Splunk webhook envelope: stable rule plus an explicit result entity.
  IF coalesce(p->>'search_name','') <> '' AND p ? 'result' THEN
   p := jsonb_build_object('source','splunk','rule',p->>'search_name',
    'entity',coalesce(nullif(p->'result'->>'entity',''),nullif(p->'result'->>'host',''),
     p->>'sid',e->>'id'),
    'status',coalesce(p->'result'->>'status','firing'),
    'impact',coalesce(p->'result'->>'impact','unknown'),
    'summary',coalesce(p->'result'->>'summary',p->>'search_name'),
    'details_url',p->>'results_link');
  END IF;
  -- Canonical producer contract. Unknown identity never merges unrelated entities.
  IF coalesce(p->>'source','') <> '' AND coalesce(p->>'rule','') <> '' AND coalesce(p->>'entity','') <> '' THEN
   src := p->>'source'; rule_name := p->>'rule'; entity_name := p->>'entity'; imp := coalesce(p->>'impact','unknown');
  ELSE
   src := e->>'topic'; rule_name := 'unclassified'; entity_name := e->>'id'; imp := 'unknown';
  END IF;
  sev := coalesce(p->>'severity',CASE e->>'priority' WHEN '5' THEN 'critical' WHEN '4' THEN 'high' WHEN '2' THEN 'low' WHEN '1' THEN 'minimum' ELSE 'normal' END);
  firing := coalesce(p->>'status','firing') NOT IN ('resolved','recovered','ok');
  detail := coalesce(nullif(p->>'details_url',''), e->'attachment'->>'url', e->>'click');
  IF coalesce(detail,'') !~ '^https?://[^<>[:space:]]+$' OR length(detail) > 2048 THEN detail := NULL; END IF;
  safe_title := left(replace(replace(replace(coalesce(p->>'summary',p->>'title',e->>'title',rule_name),'&','&amp;'),'<','&lt;'),'>','&gt;'),1500);
  k := md5(jsonb_build_array(src,rule_name,entity_name)::text);
  urgent := firing AND imp = ANY(allowed_impacts) AND (src || ':' || rule_name) = ANY(allowed_rules);
  PERFORM pg_advisory_xact_lock(hashtextextended(k,0));
  SELECT * INTO previous FROM alert_delivery.incident WHERE key=k;
  INSERT INTO alert_delivery.incident(key,source,rule,entity,title,impact,critical,active,details_url,severity,events)
   VALUES(k,src,rule_name,entity_name,safe_title,imp,urgent,firing,detail,sev,1)
   ON CONFLICT(key) DO UPDATE SET events=alert_delivery.incident.events+1,last_seen=now(),impact=imp,
    critical=urgent,title=excluded.title,active=firing,details_url=detail,severity=sev;
  IF previous.key IS NULL OR (firing AND NOT previous.active) THEN
   INSERT INTO alert_delivery.notification(incident_key,channel,kind,body,delivery_key)
    VALUES(k,'general','initial',safe_title||coalesce(' '||detail,'')||' ['||k||']','general:'||k||':'||(e->>'id'));
   UPDATE alert_delivery.incident SET last_general=now(),last_general_events=events WHERE key=k;
  END IF;
  IF urgent AND (previous.key IS NULL OR NOT previous.critical) THEN
   INSERT INTO alert_delivery.notification(incident_key,channel,kind,body,delivery_key)
    VALUES(k,'critical','escalation','<!channel> '||safe_title||coalesce(' '||detail,'')||' ['||k||']',
     'critical:'||(e->>'topic')||':'||(e->>'id'));
   UPDATE alert_delivery.incident SET last_critical=now() WHERE key=k;
  END IF;
  IF NOT firing THEN
   UPDATE alert_delivery.notification SET cancelled_at=now() WHERE incident_key=k AND channel='critical' AND kind='reminder' AND acknowledged_at IS NULL;
   IF previous.critical THEN
    INSERT INTO alert_delivery.notification(incident_key,channel,kind,body,delivery_key)
     VALUES(k,'critical','recovery','Recovery observed: '||safe_title,
      'critical-recovery:'||(e->>'topic')||':'||(e->>'id'));
   END IF;
   IF previous.active THEN
    INSERT INTO alert_delivery.notification(incident_key,channel,kind,body,delivery_key)
     VALUES(k,'general','recovery','Recovery observed: '||safe_title||coalesce(' '||detail,''),
      'recovery:'||(e->>'topic')||':'||(e->>'id'));
   END IF;
  END IF;
  INSERT INTO alert_delivery.ticket(incident_key,operation_key,body)
   VALUES(k,md5(jsonb_build_array(e->>'topic',e->>'id')::text),
    'Severity: '||left(sev,40)||E'\n'||
    left(coalesce(e->>'message',''),3800-length(coalesce(detail,'')))||coalesce(E'\nEvidence: '||detail,''));
  INSERT INTO alert_delivery.enrichment(incident_key) VALUES(k) ON CONFLICT DO NOTHING;
  INSERT INTO alert_delivery.cursor VALUES(e->>'topic',(e->>'time')::bigint)
   ON CONFLICT(topic) DO UPDATE SET seen=greatest(alert_delivery.cursor.seen,excluded.seen);
  total := total+1;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR invalid_parameter_value THEN
   INSERT INTO alert_delivery.quarantine(fingerprint,sample,error_code)
    VALUES(md5(line),left(line,1024),SQLSTATE)
    ON CONFLICT(fingerprint) DO UPDATE SET last_seen=now(),occurrences=alert_delivery.quarantine.occurrences+1;
  END;
 END LOOP;
 RETURN total;
END $$;

CREATE OR REPLACE FUNCTION alert_delivery.periodic() RETURNS void LANGUAGE plpgsql AS $$
DECLARE i alert_delivery.incident%ROWTYPE; retention_days integer := 14;
BEGIN
 IF retention_days < 7 THEN RAISE EXCEPTION 'retention must cover the replay cache (at least seven days)'; END IF;
 -- Retain unresolved work; only completed payloads expire. Bounded batches avoid long polling locks.
 DELETE FROM alert_delivery.message WHERE (topic,id) IN
  (SELECT topic,id FROM alert_delivery.message WHERE happened < extract(epoch FROM now()-make_interval(days=>retention_days)) LIMIT 10000);
 DELETE FROM alert_delivery.notification WHERE id IN
  (SELECT n.id FROM alert_delivery.notification n WHERE coalesce(n.acknowledged_at,n.cancelled_at) < now()-make_interval(days=>retention_days)
   AND (n.kind <> 'initial' OR NOT EXISTS(SELECT 1 FROM alert_delivery.incident inc WHERE inc.key=n.incident_key AND (inc.active OR inc.last_seen >= now()-make_interval(days=>retention_days)))) LIMIT 10000);
 DELETE FROM alert_delivery.ticket WHERE id IN
  (SELECT id FROM alert_delivery.ticket WHERE acknowledged_at < now()-make_interval(days=>retention_days) LIMIT 10000);
 DELETE FROM alert_delivery.quarantine WHERE fingerprint IN
  (SELECT fingerprint FROM alert_delivery.quarantine ORDER BY last_seen DESC OFFSET 10000 LIMIT 10000);
 DELETE FROM alert_delivery.quarantine WHERE last_seen < now()-make_interval(days=>retention_days);
 DELETE FROM alert_delivery.enrichment WHERE acknowledged_at < now()-make_interval(days=>retention_days)
  AND incident_key IN (SELECT key FROM alert_delivery.incident WHERE NOT active AND last_seen < now()-make_interval(days=>retention_days));
 DELETE FROM alert_delivery.incident WHERE key IN
  (SELECT old_incident.key FROM alert_delivery.incident old_incident WHERE NOT old_incident.active AND old_incident.last_seen < now()-make_interval(days=>retention_days)
   AND NOT EXISTS(SELECT 1 FROM alert_delivery.ticket t WHERE t.incident_key=old_incident.key)
   AND NOT EXISTS(SELECT 1 FROM alert_delivery.notification n WHERE n.incident_key=old_incident.key)
   AND NOT EXISTS(SELECT 1 FROM alert_delivery.enrichment e WHERE e.incident_key=old_incident.key) LIMIT 10000);


 FOR i IN SELECT * FROM alert_delivery.incident WHERE active FOR UPDATE SKIP LOCKED LOOP
  IF i.last_general <= now()-interval '30 minutes' AND i.events > i.last_general_events THEN
   INSERT INTO alert_delivery.notification(incident_key,channel,kind,body,delivery_key)
    VALUES(i.key,'general','digest',i.title||': '||i.events||' observations ['||i.key||']',
     'digest:'||i.key||':'||extract(epoch FROM now())::text);
   UPDATE alert_delivery.incident SET last_general=now(),last_general_events=events WHERE key=i.key;
  END IF;
  IF i.critical AND i.last_critical <= now()-interval '30 minutes' THEN
   INSERT INTO alert_delivery.notification(incident_key,channel,kind,body,delivery_key)
    VALUES(i.key,'critical','reminder','<!channel> '||i.title||': awaiting explicit recovery; last observed '||i.last_seen||' ['||i.key||']',
     'reminder:'||i.key||':'||extract(epoch FROM now())::text);
   UPDATE alert_delivery.incident SET last_critical=now() WHERE key=i.key;
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION alert_delivery.claim_notification(target text)
RETURNS SETOF alert_delivery.notification LANGUAGE plpgsql AS $$
DECLARE b alert_delivery.budget%ROWTYPE; cap integer; ids bigint[]; summary text; n alert_delivery.notification%ROWTYPE;
BEGIN
 cap := CASE target WHEN 'general' THEN 5 WHEN 'critical' THEN 3 ELSE 0 END;
 IF cap=0 THEN RAISE EXCEPTION 'invalid channel'; END IF;
 INSERT INTO alert_delivery.budget VALUES(target,now(),0) ON CONFLICT DO NOTHING;
 SELECT * INTO b FROM alert_delivery.budget WHERE channel=target FOR UPDATE;
 IF b.window_started <= now()-interval '1 minute' THEN
  UPDATE alert_delivery.budget SET window_started=now(),used=0 WHERE channel=target; b.used:=0;
 END IF;
 IF b.used>=cap THEN RETURN; END IF;
 -- One worker per channel keeps reconciliation ordered and bounds concurrent sends.
 IF EXISTS(SELECT 1 FROM alert_delivery.notification WHERE channel=target AND acknowledged_at IS NULL AND cancelled_at IS NULL AND lease_until>now()) THEN RETURN; END IF;
 SELECT * INTO n FROM alert_delivery.notification WHERE channel=target AND acknowledged_at IS NULL AND cancelled_at IS NULL
  AND available_at<=now() AND (lease_until IS NULL OR lease_until<=now()) ORDER BY id LIMIT 1 FOR UPDATE;
 IF n.id IS NULL THEN RETURN; END IF;
 -- Group only never-attempted rows. Ambiguous operations keep their original identifier.
 IF n.attempts=0 THEN
  SELECT array_agg(id) INTO ids FROM alert_delivery.notification WHERE channel=target
   AND acknowledged_at IS NULL AND cancelled_at IS NULL AND attempts=0 AND NOT grouped AND available_at<=now();
  IF cardinality(ids)>cap-b.used THEN
   SELECT string_agg(left(body,420),E'\n') INTO summary FROM (SELECT body FROM alert_delivery.notification WHERE id=ANY(ids) ORDER BY id LIMIT 8) sample;
   WITH deferred AS (SELECT id,row_number() OVER (ORDER BY id) AS position FROM alert_delivery.notification WHERE id=ANY(ids))
    UPDATE alert_delivery.notification q SET grouped=true,available_at=now()+interval '1 minute'*(1+(d.position-1)/cap)
    FROM deferred d WHERE q.id=d.id;
   INSERT INTO alert_delivery.notification(channel,kind,body,delivery_key,grouped)
    VALUES(target,'overflow',(CASE WHEN target='critical' THEN '<!channel> ' ELSE '' END)
     ||cardinality(ids)||' grouped updates; individual incident threads follow at the channel budget.'||E'\n'||summary,
     'overflow:'||target||':'||n.id,true) RETURNING * INTO n;
  END IF;
 END IF;
 UPDATE alert_delivery.budget SET used=used+1 WHERE channel=target;
 RETURN QUERY UPDATE alert_delivery.notification SET lease_until=now()+interval '2 minutes',
  available_at=now()+make_interval(secs=>least(3600,120*power(2,least(attempts,5)))::integer),attempts=attempts+1,
  uncertain=(attempts>0) WHERE id=n.id RETURNING *;
END $$;

CREATE OR REPLACE FUNCTION alert_delivery.claim_ticket()
RETURNS SETOF alert_delivery.ticket LANGUAGE sql AS $$
 WITH candidate AS (
  SELECT t.id FROM alert_delivery.ticket t WHERE t.acknowledged_at IS NULL AND t.available_at<=now()
   AND (t.lease_until IS NULL OR t.lease_until<=now())
   AND NOT EXISTS(SELECT 1 FROM alert_delivery.ticket prior WHERE prior.incident_key=t.incident_key
    AND prior.acknowledged_at IS NULL AND prior.id<t.id)
  ORDER BY t.id FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE alert_delivery.ticket t SET lease_until=now()+interval '5 minutes',
 available_at=now()+make_interval(secs=>least(3600,300*power(2,least(attempts,4)))::integer),attempts=attempts+1
 FROM candidate c WHERE t.id=c.id RETURNING t.*;
$$;
