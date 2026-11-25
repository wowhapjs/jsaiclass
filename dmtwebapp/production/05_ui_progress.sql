BEGIN;
SET LOCAL search_path=dmtwebapp,pg_catalog;
ALTER TABLE apps DROP CONSTRAINT IF EXISTS apps_folder_name_check;
ALTER TABLE apps ADD CONSTRAINT apps_folder_name_check CHECK(folder_name ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$' AND lower(folder_name) NOT IN ('api','versions','login','logout','admin','assets','trial'));
CREATE UNIQUE INDEX IF NOT EXISTS apps_student_folder_ci ON apps(student_id,lower(folder_name));
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS request_key uuid;
CREATE UNIQUE INDEX IF NOT EXISTS uploads_student_request ON uploads(student_id,request_key) WHERE request_key IS NOT NULL;
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS build_phase text NOT NULL DEFAULT 'queued';
UPDATE uploads SET build_phase=CASE status WHEN 'ready' THEN 'ready' WHEN 'failed' THEN 'failed' WHEN 'validating' THEN 'inspect' WHEN 'deleted' THEN 'deleted' ELSE 'queued' END;
CREATE OR REPLACE FUNCTION dashboard(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE sid bigint:=session_student(p->>'token'); result jsonb;
 BEGIN
 IF sid IS NULL THEN RETURN '{"error":"AUTH_REQUIRED"}'::jsonb; END IF;
 SELECT jsonb_build_object('folder',st.folder_id,'language',st.preferred_language,
 'storage_bytes',(SELECT COALESCE(sum(zip_bytes+COALESCE(extracted_bytes,0)),0) FROM uploads WHERE student_id=sid), 'storage_limit',536870912,
 'apps',COALESCE((SELECT jsonb_agg(jsonb_build_object('folder',a.folder_name,'name',a.app_name,
 'active', (SELECT version_number FROM uploads WHERE id=a.active_upload_id),
 'host','dmt-'||replace(a.id::text,'-','')||'.jsaiclass.duckdns.org',
 'versions',COALESCE((SELECT jsonb_agg(jsonb_build_object('version',u.version_number,'filename',u.original_filename,'title',u.version_title,
 'notes',u.release_notes,'state',u.status,'bytes',u.zip_bytes,'error',u.error_message,'created',u.uploaded_at,
 'database',u.db_mode,'phase',u.build_phase,'extracted_bytes',u.extracted_bytes,'updated',u.updated_at,'config',u.public_config,'entry',u.entry_path,'request_key',u.request_key) ORDER BY u.version_number DESC) FROM uploads u WHERE u.app_id=a.id AND u.status<>'deleted'),'[]'::jsonb))
 ORDER BY a.created_at DESC) FROM apps a WHERE a.student_id=st.id AND a.deleted_at IS NULL),'[]'::jsonb))
 INTO result FROM students st WHERE id=sid;
 RETURN result;
 END $$;
CREATE OR REPLACE FUNCTION enqueue(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE sid bigint:=session_student(p->>'token'); a apps%ROWTYPE; v integer; u uuid; prior uploads%ROWTYPE; b bigint:=(p->>'bytes')::bigint;
 BEGIN
 IF sid IS NULL THEN RETURN '{"error":"AUTH_REQUIRED"}'::jsonb; END IF;
 IF b<1 OR b>52428800 THEN RETURN '{"error":"ZIP_SIZE_LIMIT"}'::jsonb; END IF;
 PERFORM pg_advisory_xact_lock(735100);
 SELECT * INTO prior FROM uploads WHERE student_id=sid AND request_key=(p->>'request_key')::uuid;
 IF FOUND THEN
  RETURN jsonb_build_object('version',prior.version_number,'status',prior.status,'folder',(SELECT folder_name FROM apps WHERE id=prior.app_id),'reused_request',true);
 END IF;
 IF (SELECT count(*) FROM uploads WHERE status IN ('uploaded','validating'))>=24 THEN RETURN '{"error":"QUEUE_FULL"}'::jsonb; END IF;
 IF (SELECT count(*) FROM uploads WHERE student_id=sid AND status IN ('uploaded','validating'))>=2 THEN RETURN '{"error":"STUDENT_QUEUE_FULL"}'::jsonb; END IF;
 IF (SELECT COALESCE(sum(zip_bytes+COALESCE(extracted_bytes,0)),0) FROM uploads WHERE student_id=sid)+b>536870912 THEN RETURN '{"error":"STORAGE_LIMIT"}'::jsonb; END IF;
 SELECT * INTO a FROM apps WHERE student_id=sid AND lower(folder_name)=lower(p->>'folder') FOR UPDATE;
 IF NOT FOUND THEN
  IF (SELECT count(*) FROM apps WHERE student_id=sid)>=8 THEN RETURN '{"error":"APP_LIMIT"}'::jsonb; END IF;
  INSERT INTO apps(student_id,folder_name,app_name) VALUES(sid,p->>'folder',p->>'name') RETURNING * INTO a;
 ELSIF a.deleted_at IS NOT NULL THEN
  UPDATE apps SET deleted_at=NULL,app_name=p->>'name' WHERE id=a.id;
 END IF;
 IF (SELECT count(*) FROM uploads WHERE app_id=a.id)>=24 THEN RETURN '{"error":"VERSION_LIMIT"}'::jsonb; END IF;
 IF EXISTS(SELECT 1 FROM uploads WHERE app_id=a.id AND status IN ('uploaded','validating')) THEN RETURN '{"error":"APP_BUSY"}'::jsonb; END IF;
 v:=a.next_version;
 UPDATE apps SET next_version=v+1 WHERE id=a.id;
 INSERT INTO uploads(student_id,app_id,version_number,original_filename,storage_key,zip_bytes,version_title,release_notes,public_config,request_key)
 VALUES(sid,a.id,v,p->>'filename',(p->>'storage')::uuid,b,left(p->>'title',100),left(p->>'notes',1000),COALESCE(p->'config','{}'),(p->>'request_key')::uuid) RETURNING id INTO u;
 INSERT INTO events(student_id,upload_id,action,detail) VALUES(sid,u,'queued',jsonb_build_object('version',v));
 RETURN jsonb_build_object('version',v,'status','uploaded','folder',a.folder_name);
 END $$;
CREATE OR REPLACE FUNCTION student_action(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE sid bigint:=session_student(p->>'token'); a apps%ROWTYPE; u uploads%ROWTYPE; op text:=p->>'action';
 BEGIN
 IF sid IS NULL THEN RETURN '{"error":"AUTH_REQUIRED"}'::jsonb; END IF;
 IF op='logout' THEN DELETE FROM sessions WHERE token_hash=p->>'token'; RETURN '{"ok":true}'::jsonb; END IF;
 IF op='language' THEN UPDATE students SET preferred_language=p->>'language' WHERE id=sid AND p->>'language' IN ('en','ko'); RETURN '{"ok":true}'::jsonb; END IF;
 SELECT * INTO a FROM apps WHERE student_id=sid AND lower(folder_name)=lower(p->>'folder') AND deleted_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RETURN '{"error":"APP_NOT_FOUND"}'::jsonb; END IF;
 IF op='delete_app' THEN
  IF EXISTS(SELECT 1 FROM uploads WHERE app_id=a.id AND status IN ('uploaded','validating')) THEN RETURN '{"error":"APP_BUSY"}'::jsonb; END IF;
  UPDATE apps SET active_upload_id=NULL,deleted_at=now() WHERE id=a.id;
  UPDATE uploads SET status='deleted',deleted_at=now(),updated_at=now() WHERE app_id=a.id AND status<>'deleted';
  INSERT INTO events(student_id,action,detail) VALUES(sid,op,jsonb_build_object('app',a.id));
  RETURN '{"ok":true}'::jsonb;
 END IF;
 SELECT * INTO u FROM uploads WHERE app_id=a.id AND version_number=(p->>'version')::integer FOR UPDATE;
 IF NOT FOUND THEN RETURN '{"error":"VERSION_NOT_FOUND"}'::jsonb; END IF;
 IF op IN ('serve','rollback') THEN
  IF u.status<>'ready' OR u.artifact_key IS NULL THEN RETURN '{"error":"VERSION_NOT_READY"}'::jsonb; END IF;
  IF op='rollback' AND (a.active_upload_id IS NULL OR u.version_number >= (SELECT version_number FROM uploads WHERE id=a.active_upload_id)) THEN RETURN '{"error":"INVALID_ROLLBACK_TARGET"}'::jsonb; END IF;
  UPDATE apps SET active_upload_id=u.id WHERE id=a.id;
 ELSIF op='delete' THEN
  IF u.id=a.active_upload_id THEN RETURN '{"error":"ACTIVE_VERSION_CANNOT_DELETE"}'::jsonb; END IF;
  IF u.status NOT IN ('ready','failed') THEN RETURN '{"error":"VERSION_NOT_READY"}'::jsonb; END IF;
  UPDATE uploads SET status='deleted',deleted_at=now(),updated_at=now() WHERE id=u.id;
 ELSE RETURN '{"error":"BAD_ACTION"}'::jsonb;
 END IF;
 INSERT INTO events(student_id,upload_id,action) VALUES(sid,u.id,op);
 RETURN '{"ok":true}'::jsonb;
 END $$;
CREATE OR REPLACE FUNCTION resolve_app(p jsonb) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 SELECT jsonb_build_object('app',a.id,'artifact',u.artifact_key,'database',u.db_mode,
 'host','dmt-'||replace(a.id::text,'-','')||'.jsaiclass.duckdns.org','version',u.version_number,'config',u.public_config)
 FROM apps a JOIN students s ON s.id=a.student_id AND s.active JOIN uploads u ON u.app_id=a.id AND u.status='ready'
 WHERE a.deleted_at IS NULL AND (CASE WHEN p ? 'host' THEN 'dmt-'||replace(a.id::text,'-','')||'.jsaiclass.duckdns.org'=p->>'host'
 ELSE s.folder_id=p->>'student' AND a.lower(folder_name)=lower(p->>'folder') END)
 AND (CASE WHEN p ? 'version' THEN u.version_number=(p->>'version')::integer ELSE u.id=a.active_upload_id END)
$$;
CREATE OR REPLACE FUNCTION claim_job(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE u uploads%ROWTYPE;
 BEGIN
 UPDATE uploads SET status='failed',build_phase='failed',error_message='WORKER_INTERRUPTED',updated_at=now()
 WHERE status='validating' AND claimed_at<now()-interval '30 min';
 SELECT * INTO u FROM uploads WHERE status='uploaded' ORDER BY uploaded_at LIMIT 1 FOR UPDATE SKIP LOCKED;
 IF NOT FOUND THEN RETURN '{}'::jsonb; END IF;
 UPDATE uploads SET status='validating',build_phase='inspect',claimed_at=now(),updated_at=now() WHERE id=u.id;
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
   UPDATE uploads SET status='failed',build_phase='failed',error_message='STORAGE_LIMIT',updated_at=now() WHERE id=u.id;
   RETURN '{"error":"STORAGE_LIMIT"}'::jsonb;
  END IF;
  UPDATE uploads SET status='ready',build_phase='ready',artifact_key=(p->>'artifact')::uuid,extracted_bytes=(p->>'bytes')::bigint,entry_path='index.html',
  sha256=p->>'sha',build_key=p->>'key',db_mode=p->>'database',public_config=COALESCE(p->'config','{}'),updated_at=now() WHERE id=u.id;
  IF a.active_upload_id IS NULL AND a.deleted_at IS NULL THEN UPDATE apps SET active_upload_id=u.id WHERE id=a.id; END IF;
 ELSE UPDATE uploads SET status='failed',build_phase='failed',error_message=left(p->>'error',100),updated_at=now() WHERE id=u.id;
 END IF;
 INSERT INTO events(student_id,upload_id,action) VALUES(u.student_id,u.id,CASE WHEN p->>'status'='ready' THEN 'ready' ELSE 'failed' END);
 RETURN '{"ok":true}'::jsonb;
 END $$;
CREATE OR REPLACE FUNCTION update_phase(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
BEGIN
 IF p->>'phase' NOT IN ('inspect','build','verify','reuse') THEN RETURN '{"error":"BAD_PHASE"}'::jsonb; END IF;
 UPDATE uploads SET build_phase=p->>'phase',updated_at=now() WHERE id=(p->>'id')::uuid AND status='validating';
 RETURN jsonb_build_object('ok',FOUND);
END $$;
REVOKE ALL ON FUNCTION update_phase(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_phase(jsonb) TO dmtworker;
COMMIT;
