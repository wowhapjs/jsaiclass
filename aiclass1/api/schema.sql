-- Dedicated aiclass1 database. Apply via psql as aiclassapp.
CREATE TABLE IF NOT EXISTS participants (
 id bigserial PRIMARY KEY, phone_e164 varchar(20) NOT NULL UNIQUE,
 display_name varchar(80) NOT NULL, active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
 id bigserial PRIMARY KEY, participant_id bigint NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
 token_hash char(64) NOT NULL UNIQUE, expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS videos (
 id smallint PRIMARY KEY, order_no smallint NOT NULL UNIQUE,
 title varchar(100) NOT NULL, source_type varchar(8) NOT NULL CHECK (source_type IN ('FLOW','DRIVE')),
 source_ref varchar(100) NOT NULL UNIQUE, share_url text NOT NULL,
 media_uuid uuid
);
CREATE TABLE IF NOT EXISTS hearts (
 participant_id bigint NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
 video_id smallint NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(participant_id,video_id)
);
CREATE INDEX IF NOT EXISTS hearts_video_idx ON hearts(video_id);
CREATE TABLE IF NOT EXISTS comments (
 id bigserial PRIMARY KEY, video_id smallint NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
 participant_id bigint NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
 parent_id bigint REFERENCES comments(id) ON DELETE CASCADE, body varchar(500) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE INDEX IF NOT EXISTS comments_video_idx ON comments(video_id,created_at DESC);
CREATE TABLE IF NOT EXISTS video_progress (
 participant_id bigint PRIMARY KEY REFERENCES participants(id) ON DELETE CASCADE,
 last_video_id smallint REFERENCES videos(id), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS video_source_cache (
 video_id smallint PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
 resolved_url text NOT NULL, expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS event_config (
 id integer PRIMARY KEY DEFAULT 1 CHECK (id=1),
 max_hearts integer NOT NULL DEFAULT 5 CHECK(max_hearts BETWEEN 1 AND 14),
 comments_enabled boolean NOT NULL DEFAULT true
);
INSERT INTO event_config(id,max_hearts,comments_enabled) VALUES(1,5,true) ON CONFLICT(id) DO NOTHING;
-- Phone allowlist is imported privately during deployment; never commit personal data.
-- Participant 13-14 are provisioned through a production-only parameterized allowlist migration.
INSERT INTO videos(id,order_no,title,source_type,source_ref,share_url) VALUES
(1,1,'Product 01','DRIVE','1Zh23cFQYlt-jCXiCSgKAAE1ijUWt-0Nn','https://drive.google.com/file/d/1Zh23cFQYlt-jCXiCSgKAAE1ijUWt-0Nn/view?usp=drivesdk'),
(2,2,'Product 02','DRIVE','1ny61flJI7jiE1iOlNS1CXiNE8Lj-rmCy','https://drive.google.com/file/d/1ny61flJI7jiE1iOlNS1CXiNE8Lj-rmCy/view?usp=drivesdk'),
(3,3,'Product 03','DRIVE','1oMvVuEwy5MYcyisNDAdE8-zDijwreG5f','https://drive.google.com/file/d/1oMvVuEwy5MYcyisNDAdE8-zDijwreG5f/view?usp=drivesdk'),
(4,4,'Product 04','DRIVE','1-0d5idQ-XoyD7JDQs4ojH2QpkY-zvQ_N','https://drive.google.com/file/d/1-0d5idQ-XoyD7JDQs4ojH2QpkY-zvQ_N/view?usp=drivesdk'),
(5,5,'Product 05','DRIVE','132VU4R12ljmjKVzHd_Bsbn-6f8aIsC9b','https://drive.google.com/file/d/132VU4R12ljmjKVzHd_Bsbn-6f8aIsC9b/view?usp=drivesdk'),
(6,6,'Product 06','DRIVE','1v3e-pK7HKiTibS1FpDaMYmhhtslueHMs','https://drive.google.com/file/d/1v3e-pK7HKiTibS1FpDaMYmhhtslueHMs/view?usp=drivesdk'),
(7,7,'Product 07','DRIVE','1C0T8_erBlY_gbdMMBJRXyhdi0NzSBlR3','https://drive.google.com/file/d/1C0T8_erBlY_gbdMMBJRXyhdi0NzSBlR3/view?usp=drivesdk'),
(8,8,'Product 08','DRIVE','1D8x7n_v7ccl6miLrCDezYEfFNFlqMgZ5','https://drive.google.com/file/d/1D8x7n_v7ccl6miLrCDezYEfFNFlqMgZ5/view?usp=drive_link'),
(9,9,'Product 09','DRIVE','1UYpzhgQieIAHxop72mgx0ANSNmYb8Uie','https://drive.google.com/file/d/1UYpzhgQieIAHxop72mgx0ANSNmYb8Uie/view?usp=drive_link'),
(10,10,'Product 10','DRIVE','1InKf-jbKeibQaKQJZtzvlgctfO390l1l','https://drive.google.com/file/d/1InKf-jbKeibQaKQJZtzvlgctfO390l1l/view?usp=drivesdk'),
(11,11,'Product 11','DRIVE','1WU8V24LzEIJaSoOQHrwjqae0jQrNroE7','https://drive.google.com/file/d/1WU8V24LzEIJaSoOQHrwjqae0jQrNroE7/view?usp=drive_link'),
(12,12,'Product 12','DRIVE','1cJBaxqK_zwKBi05fVVST1N6efws8BoG1','https://drive.google.com/file/d/1cJBaxqK_zwKBi05fVVST1N6efws8BoG1/view?usp=drive_link'),
(13,13,'Product 13','DRIVE','1inzeJqL6csen7yNo9FoTxbeWz78x5XW0','https://drive.google.com/file/d/1inzeJqL6csen7yNo9FoTxbeWz78x5XW0/view?usp=drive_link'),
(14,14,'Product 14','DRIVE','19YAQdYdnw5THIgEbJCV3Lncd-IKbbTGf','https://drive.google.com/file/d/19YAQdYdnw5THIgEbJCV3Lncd-IKbbTGf/view?usp=drivesdk')
ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,source_type=EXCLUDED.source_type,source_ref=EXCLUDED.source_ref,share_url=EXCLUDED.share_url;

-- Stable media IDs are metadata only; playback requires refreshed expiring signed URLs.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS media_uuid uuid;
UPDATE videos SET media_uuid='d29cd732-c9c0-4700-a32c-0b5c2ee52225'::uuid WHERE id=1 AND source_type='FLOW';
UPDATE videos SET media_uuid='3614699a-6f5d-44c3-bef9-bb6efc516a56'::uuid WHERE id=2 AND source_type='FLOW';
UPDATE videos SET media_uuid='4f81d04d-7405-471f-9d39-1eff5ffcb26f'::uuid WHERE id=3 AND source_type='FLOW';
UPDATE videos SET media_uuid='de6ef672-9259-41e3-8bf6-23393e0e0717'::uuid WHERE id=4 AND source_type='FLOW';
UPDATE videos SET media_uuid='951fe3a9-73d7-46ec-851d-61509099303f'::uuid WHERE id=5 AND source_type='FLOW';
UPDATE videos SET media_uuid='0d92d4cb-10dd-4a7c-9749-145cccef2a86'::uuid WHERE id=6 AND source_type='FLOW';
UPDATE videos SET media_uuid='50deddb0-d926-47e4-bb06-3f04e638ecef'::uuid WHERE id=7 AND source_type='FLOW';
UPDATE videos SET media_uuid='2c711204-f38f-43fe-b35a-e767731dfee5'::uuid WHERE id=10 AND source_type='FLOW';

-- The eight rehosted Flow works now use Drive file IDs, not Flow's expiring links.
UPDATE videos SET media_uuid=NULL WHERE source_type='DRIVE' AND media_uuid IS NOT NULL;
