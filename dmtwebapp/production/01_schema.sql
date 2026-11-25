BEGIN;
SET LOCAL search_path=dmtwebapp,pg_catalog;
CREATE TABLE IF NOT EXISTS apps (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 student_id bigint NOT NULL REFERENCES students(id),
 folder_name text NOT NULL CHECK(folder_name ~ '^[a-z0-9][a-z0-9_-]{0,39}$' AND folder_name NOT IN ('api','versions','login','logout','admin','assets','trial')),
 app_name text NOT NULL CHECK(length(app_name) BETWEEN 1 AND 100),
 active_upload_id uuid REFERENCES uploads(id),
 next_version integer NOT NULL DEFAULT 1,
 deleted_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(student_id,folder_name)
);
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS app_id uuid REFERENCES apps(id);
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS version_number integer;
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS version_title text NOT NULL DEFAULT '';
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS release_notes text NOT NULL DEFAULT '';
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS artifact_key uuid;
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS build_key text;
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS db_mode text NOT NULL DEFAULT 'none';
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS public_config jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS upload_app_version ON uploads(app_id,version_number);
CREATE INDEX IF NOT EXISTS upload_build_cache ON uploads(app_id,build_key,status);
CREATE INDEX IF NOT EXISTS upload_queue ON uploads(uploaded_at) WHERE status='uploaded';
CREATE TABLE IF NOT EXISTS sessions (
 token_hash text PRIMARY KEY CHECK(token_hash ~ '^[a-f0-9]{64}$'),
 student_id bigint NOT NULL REFERENCES students(id),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '12 hours'
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS login_limits (ip_hash text PRIMARY KEY, attempts integer NOT NULL, start_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS app_browser_data (
 app_id uuid REFERENCES apps(id), browser_hash text NOT NULL,
 data_key text NOT NULL CHECK(length(data_key) BETWEEN 1 AND 100),
 value jsonb NOT NULL CHECK(octet_length(value::text)<=65536),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(app_id,browser_hash,data_key)
);
REVOKE ALL ON ALL TABLES IN SCHEMA dmtwebapp FROM PUBLIC;
GRANT USAGE ON SCHEMA dmtwebapp TO dmtapi,dmtworker;
GRANT CONNECT ON DATABASE dmtwebapp TO dmtapi,dmtworker;
COMMIT;
