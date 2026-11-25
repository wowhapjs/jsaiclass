BEGIN;
SET LOCAL search_path=dmtwebapp,pg_catalog;
CREATE OR REPLACE FUNCTION student_action(p jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 DECLARE sid bigint:=session_student(p->>'token'); a apps%ROWTYPE; u uploads%ROWTYPE; op text:=p->>'action';
 BEGIN
 IF sid IS NULL THEN RETURN '{"error":"AUTH_REQUIRED"}'::jsonb; END IF;
 IF op='logout' THEN DELETE FROM sessions WHERE token_hash=p->>'token'; RETURN '{"ok":true}'::jsonb; END IF;
 IF op='language' THEN UPDATE students SET preferred_language=p->>'language' WHERE id=sid AND p->>'language' IN ('en','ko'); RETURN '{"ok":true}'::jsonb; END IF;
 SELECT * INTO a FROM apps WHERE student_id=sid AND folder_name=p->>'folder' AND deleted_at IS NULL FOR UPDATE;
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
 ELSE s.folder_id=p->>'student' AND a.folder_name=p->>'folder' END)
 AND (CASE WHEN p ? 'version' THEN u.version_number=(p->>'version')::integer ELSE u.id=a.active_upload_id END)
$$;
CREATE OR REPLACE FUNCTION tls_allowed(p jsonb) RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,dmtwebapp AS $$
 SELECT jsonb_build_object('allowed',EXISTS(SELECT 1 FROM apps a JOIN students s ON s.id=a.student_id AND s.active
 WHERE a.deleted_at IS NULL AND 'dmt-'||replace(a.id::text,'-','')||'.jsaiclass.duckdns.org'=p->>'domain'
 AND EXISTS(SELECT 1 FROM uploads u WHERE u.app_id=a.id AND u.status='ready')))
$$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA dmtwebapp FROM PUBLIC;
GRANT EXECUTE ON FUNCTION student_action(jsonb),resolve_app(jsonb),tls_allowed(jsonb) TO dmtapi;
COMMIT;
