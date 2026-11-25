BEGIN;
SET LOCAL search_path=dmtwebapp,pg_catalog;
CREATE OR REPLACE FUNCTION claim_job(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE u uploads%ROWTYPE;
 BEGIN
 UPDATE uploads SET status='failed',error_message='WORKER_INTERRUPTED',updated_at=now()
 WHERE status='validating' AND claimed_at<now()-interval '30 min';
 SELECT * INTO u FROM uploads WHERE status='uploaded' ORDER BY uploaded_at LIMIT 1 FOR UPDATE SKIP LOCKED;
 IF NOT FOUND THEN RETURN '{}'::jsonb; END IF;
 UPDATE uploads SET status='validating',claimed_at=now(),updated_at=now() WHERE id=u.id;
 RETURN to_jsonb(u);
 END $$;
CREATE OR REPLACE FUNCTION find_artifact(p jsonb) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 SELECT jsonb_build_object('artifact',artifact_key,'bytes',extracted_bytes,'database',db_mode)
 FROM uploads WHERE app_id=(p->>'app')::uuid AND build_key=p->>'key' AND status='ready' AND artifact_key IS NOT NULL ORDER BY version_number DESC LIMIT 1
$$;
CREATE OR REPLACE FUNCTION finish_job(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE u uploads%ROWTYPE; a apps%ROWTYPE; total bigint;
 BEGIN
 SELECT * INTO u FROM uploads WHERE id=(p->>'id')::uuid AND status='validating' FOR UPDATE;
 IF NOT FOUND THEN RETURN '{"error":"JOB_NOT_CLAIMED"}'::jsonb; END IF;
 SELECT * INTO a FROM apps WHERE id=u.app_id FOR UPDATE;
 IF p->>'status'='ready' THEN
  SELECT COALESCE(sum(zip_bytes+COALESCE(extracted_bytes,0)),0) INTO total FROM uploads WHERE student_id=u.student_id;
  IF total+(p->>'bytes')::bigint>536870912 THEN
   UPDATE uploads SET status='failed',error_message='STORAGE_LIMIT',updated_at=now() WHERE id=u.id;
   RETURN '{"error":"STORAGE_LIMIT"}'::jsonb;
  END IF;
  UPDATE uploads SET status='ready',artifact_key=(p->>'artifact')::uuid,extracted_bytes=(p->>'bytes')::bigint,entry_path='index.html',
  sha256=p->>'sha',build_key=p->>'key',db_mode=p->>'database',public_config=COALESCE(p->'config','{}'),updated_at=now() WHERE id=u.id;
  IF a.active_upload_id IS NULL AND a.deleted_at IS NULL THEN UPDATE apps SET active_upload_id=u.id WHERE id=a.id; END IF;
 ELSE UPDATE uploads SET status='failed',error_message=left(p->>'error',100),updated_at=now() WHERE id=u.id;
 END IF;
 INSERT INTO events(student_id,upload_id,action) VALUES(u.student_id,u.id,CASE WHEN p->>'status'='ready' THEN 'ready' ELSE 'failed' END);
 RETURN '{"ok":true}'::jsonb;
 END $$;
CREATE OR REPLACE FUNCTION browser_data(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE aid uuid:=(p->>'app')::uuid; bh text:=p->>'browser'; k text:=p->>'key'; val jsonb;
 BEGIN
 IF NOT EXISTS(SELECT 1 FROM apps a JOIN uploads u ON u.id=a.active_upload_id WHERE a.id=aid AND a.deleted_at IS NULL AND u.db_mode='managed') THEN RETURN '{"error":"DB_NOT_ENABLED"}'::jsonb; END IF;
 IF bh !~ '^[a-f0-9]{64}$' OR length(k) NOT BETWEEN 1 AND 100 THEN RETURN '{"error":"BAD_KEY"}'::jsonb; END IF;
 IF p->>'op'='get' THEN SELECT value INTO val FROM app_browser_data WHERE app_id=aid AND browser_hash=bh AND data_key=k; RETURN jsonb_build_object('value',val); END IF;
 IF p->>'op'='put' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(aid::text,0));
  IF (SELECT count(*) FROM app_browser_data WHERE app_id=aid)>=500 OR (SELECT COALESCE(sum(octet_length(value::text)),0) FROM app_browser_data WHERE app_id=aid)+octet_length((p->'value')::text)>10485760 THEN RETURN '{"error":"DB_QUOTA"}'::jsonb; END IF;
  INSERT INTO app_browser_data(app_id,browser_hash,data_key,value) VALUES(aid,bh,k,p->'value') ON CONFLICT(app_id,browser_hash,data_key) DO UPDATE SET value=excluded.value,updated_at=now();
  RETURN '{"ok":true}'::jsonb;
 END IF;
 IF p->>'op'='delete' THEN DELETE FROM app_browser_data WHERE app_id=aid AND browser_hash=bh AND data_key=k; RETURN '{"ok":true}'::jsonb; END IF;
 RETURN '{"error":"BAD_ACTION"}'::jsonb;
 END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dmtwebapp FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_job(jsonb),find_artifact(jsonb),finish_job(jsonb) TO dmtworker;
GRANT EXECUTE ON FUNCTION browser_data(jsonb) TO dmtapi;
COMMIT;
