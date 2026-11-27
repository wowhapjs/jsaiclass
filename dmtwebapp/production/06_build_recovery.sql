BEGIN;
SET LOCAL search_path=dmtwebapp,pg_catalog;
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS recovery_count integer NOT NULL DEFAULT 0 CHECK(recovery_count BETWEEN 0 AND 1);
CREATE TABLE IF NOT EXISTS build_control (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),paused boolean NOT NULL DEFAULT false);
INSERT INTO build_control(singleton) VALUES(true) ON CONFLICT DO NOTHING;
REVOKE ALL ON build_control FROM PUBLIC,dmtworker,dmtapi;
CREATE OR REPLACE FUNCTION claim_job(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
DECLARE u uploads%ROWTYPE; stopped boolean;
BEGIN
 SELECT paused INTO stopped FROM build_control WHERE singleton FOR UPDATE;
 IF stopped OR EXISTS(SELECT 1 FROM uploads WHERE status='validating') THEN RETURN '{}'::jsonb; END IF;
 SELECT * INTO u FROM uploads WHERE status='uploaded' ORDER BY uploaded_at LIMIT 1 FOR UPDATE SKIP LOCKED;
 IF NOT FOUND THEN RETURN '{}'::jsonb; END IF;
 UPDATE uploads SET status='validating',build_phase='inspect',claimed_at=now(),updated_at=now(),error_message=NULL WHERE id=u.id RETURNING * INTO u;
 RETURN to_jsonb(u);
END $$;
CREATE OR REPLACE FUNCTION queued_jobs(p jsonb) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 SELECT jsonb_build_object('queued',EXISTS(SELECT 1 FROM uploads WHERE status='uploaded'),'paused',(SELECT paused FROM build_control WHERE singleton))
$$;
CREATE OR REPLACE FUNCTION capacity_wait(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
BEGIN
 UPDATE uploads SET build_phase='capacity_wait',updated_at=now() WHERE status='uploaded' AND build_phase IS DISTINCT FROM 'capacity_wait';
 RETURN '{"ok":true}'::jsonb;
END $$;
CREATE OR REPLACE FUNCTION heartbeat_job(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
BEGIN
 UPDATE uploads SET updated_at=now() WHERE id=(p->>'id')::uuid AND status='validating';
 RETURN jsonb_build_object('ok',FOUND);
END $$;
-- Invoked only by the singleton worker after obtaining its file lock and
-- confirming all owned build/resolver containers from the previous worker are gone.
CREATE OR REPLACE FUNCTION recover_jobs(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
DECLARE retried int; exhausted int;
BEGIN
 PERFORM 1 FROM build_control WHERE singleton FOR UPDATE;
 UPDATE uploads SET status='failed',build_phase='failed',error_message='WORKER_INTERRUPTED',updated_at=now()
 WHERE status='validating' AND recovery_count>=1;
 GET DIAGNOSTICS exhausted=ROW_COUNT;
 UPDATE uploads SET status='uploaded',build_phase='queued',claimed_at=NULL,error_message=NULL,recovery_count=recovery_count+1,updated_at=now()
 WHERE status='validating' AND recovery_count=0;
 GET DIAGNOSTICS retried=ROW_COUNT;
 RETURN jsonb_build_object('retried',retried,'exhausted',exhausted);
END $$;
REVOKE ALL ON FUNCTION queued_jobs(jsonb),capacity_wait(jsonb),heartbeat_job(jsonb),recover_jobs(jsonb) FROM PUBLIC,dmtapi;
GRANT EXECUTE ON FUNCTION queued_jobs(jsonb),capacity_wait(jsonb),heartbeat_job(jsonb),recover_jobs(jsonb) TO dmtworker;
COMMIT;
