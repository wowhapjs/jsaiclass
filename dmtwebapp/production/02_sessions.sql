BEGIN;
SET LOCAL search_path=dmtwebapp,pg_catalog;
CREATE OR REPLACE FUNCTION session_student(t text) RETURNS bigint
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 SELECT s.student_id FROM sessions s JOIN students st ON st.id=s.student_id
 WHERE s.token_hash=t AND s.expires_at>now() AND st.active
$$;
CREATE OR REPLACE FUNCTION login(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE a integer; st students%ROWTYPE;
 BEGIN
 INSERT INTO login_limits(ip_hash,attempts,start_at) VALUES(p->>'ip',1,now())
 ON CONFLICT(ip_hash) DO UPDATE SET attempts=CASE WHEN login_limits.start_at<now()-interval '5 min' THEN 1 ELSE login_limits.attempts+1 END,
 start_at=CASE WHEN login_limits.start_at<now()-interval '5 min' THEN now() ELSE login_limits.start_at END
 RETURNING attempts INTO a;
 IF a>40 THEN RETURN jsonb_build_object('error','RATE_LIMIT'); END IF;
 SELECT * INTO st FROM students WHERE phone_number=p->>'phone' AND active;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','LOGIN_FAILED'); END IF;
 DELETE FROM sessions WHERE expires_at<now();
 INSERT INTO sessions(token_hash,student_id) VALUES(p->>'token',st.id);
 INSERT INTO events(student_id,action) VALUES(st.id,'login');
 RETURN jsonb_build_object('folder',st.folder_id,'language',st.preferred_language);
 END $$;
CREATE OR REPLACE FUNCTION dashboard(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE sid bigint:=session_student(p->>'token'); result jsonb;
 BEGIN
 IF sid IS NULL THEN RETURN '{"error":"AUTH_REQUIRED"}'::jsonb; END IF;
 SELECT jsonb_build_object('folder',st.folder_id,'language',st.preferred_language,
 'apps',COALESCE((SELECT jsonb_agg(jsonb_build_object('folder',a.folder_name,'name',a.app_name,
 'active', (SELECT version_number FROM uploads WHERE id=a.active_upload_id),
 'host','dmt-'||replace(a.id::text,'-','')||'.jsaiclass.duckdns.org',
 'versions',COALESCE((SELECT jsonb_agg(jsonb_build_object('version',u.version_number,'filename',u.original_filename,'title',u.version_title,
 'notes',u.release_notes,'state',u.status,'bytes',u.zip_bytes,'error',u.error_message,'created',u.uploaded_at,
 'database',u.db_mode) ORDER BY u.version_number DESC) FROM uploads u WHERE u.app_id=a.id AND u.status<>'deleted'),'[]'::jsonb))
 ORDER BY a.created_at DESC) FROM apps a WHERE a.student_id=st.id AND a.deleted_at IS NULL),'[]'::jsonb))
 INTO result FROM students st WHERE id=sid;
 RETURN result;
 END $$;
CREATE OR REPLACE FUNCTION enqueue(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE sid bigint:=session_student(p->>'token'); a apps%ROWTYPE; v integer; u uuid; b bigint:=(p->>'bytes')::bigint;
 BEGIN
 IF sid IS NULL THEN RETURN '{"error":"AUTH_REQUIRED"}'::jsonb; END IF;
 IF b<1 OR b>52428800 THEN RETURN '{"error":"ZIP_SIZE_LIMIT"}'::jsonb; END IF;
 PERFORM pg_advisory_xact_lock(735100);
 IF (SELECT count(*) FROM uploads WHERE status IN ('uploaded','validating'))>=24 THEN RETURN '{"error":"QUEUE_FULL"}'::jsonb; END IF;
 IF (SELECT count(*) FROM uploads WHERE student_id=sid AND status IN ('uploaded','validating'))>=2 THEN RETURN '{"error":"STUDENT_QUEUE_FULL"}'::jsonb; END IF;
 IF (SELECT COALESCE(sum(zip_bytes+COALESCE(extracted_bytes,0)),0) FROM uploads WHERE student_id=sid)+b>536870912 THEN RETURN '{"error":"STORAGE_LIMIT"}'::jsonb; END IF;
 SELECT * INTO a FROM apps WHERE student_id=sid AND folder_name=p->>'folder' FOR UPDATE;
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
 INSERT INTO uploads(student_id,app_id,version_number,original_filename,storage_key,zip_bytes,version_title,release_notes,public_config)
 VALUES(sid,a.id,v,p->>'filename',(p->>'storage')::uuid,b,left(p->>'title',100),left(p->>'notes',1000),COALESCE(p->'config','{}')) RETURNING id INTO u;
 INSERT INTO events(student_id,upload_id,action,detail) VALUES(sid,u,'queued',jsonb_build_object('version',v));
 RETURN jsonb_build_object('version',v,'status','uploaded');
 END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dmtwebapp FROM PUBLIC;
GRANT EXECUTE ON FUNCTION login(jsonb),dashboard(jsonb),enqueue(jsonb) TO dmtapi;
COMMIT;
