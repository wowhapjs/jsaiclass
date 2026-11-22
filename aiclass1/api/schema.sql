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
 source_ref varchar(100) NOT NULL UNIQUE, share_url text NOT NULL
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
 max_hearts integer NOT NULL DEFAULT 5 CHECK(max_hearts BETWEEN 1 AND 13),
 comments_enabled boolean NOT NULL DEFAULT true
);
INSERT INTO event_config(id,max_hearts,comments_enabled) VALUES(1,5,true) ON CONFLICT(id) DO NOTHING;
-- Phone allowlist is imported privately during deployment; never commit personal data.
INSERT INTO videos(id,order_no,title,source_type,source_ref,share_url) VALUES
(1,1,'Product 01','FLOW','35c78fe9-bd93-4d78-8f57-b72282251815','https://flow.google.com/shared/video/35c78fe9-bd93-4d78-8f57-b72282251815'),
(2,2,'Product 02','FLOW','ad31d8ff-aff7-4c0f-a080-0dfe9f912198','https://flow.google.com/shared/video/ad31d8ff-aff7-4c0f-a080-0dfe9f912198'),
(3,3,'Product 03','FLOW','8c444fb6-f9d8-49f0-b2c7-a4e78f23b238','https://flow.google.com/shared/video/8c444fb6-f9d8-49f0-b2c7-a4e78f23b238'),
(4,4,'Product 04','FLOW','541c9210-984e-4071-9a72-049e33501f01','https://flow.google.com/shared/video/541c9210-984e-4071-9a72-049e33501f01'),
(5,5,'Product 05','FLOW','71a6e071-3032-416b-b4e2-a232ed3c5250','https://flow.google.com/shared/video/71a6e071-3032-416b-b4e2-a232ed3c5250'),
(6,6,'Product 06','FLOW','d64a1ccc-8b37-4fff-b6cd-a34f177c4cec','https://flow.google.com/shared/video/d64a1ccc-8b37-4fff-b6cd-a34f177c4cec'),
(7,7,'Product 07','FLOW','e5b5d449-5641-457c-9a32-c41b311660e8','https://flow.google.com/shared/video/e5b5d449-5641-457c-9a32-c41b311660e8'),
(8,8,'Product 08','DRIVE','1D8x7n_v7ccl6miLrCDezYEfFNFlqMgZ5','https://drive.google.com/file/d/1D8x7n_v7ccl6miLrCDezYEfFNFlqMgZ5/view?usp=drive_link'),
(9,9,'Product 09','DRIVE','1UYpzhgQieIAHxop72mgx0ANSNmYb8Uie','https://drive.google.com/file/d/1UYpzhgQieIAHxop72mgx0ANSNmYb8Uie/view?usp=drive_link'),
(10,10,'Product 10','FLOW','cdf0390c-ecd3-4a2e-a687-e303d6ae0dd6','https://flow.google.com/shared/video/cdf0390c-ecd3-4a2e-a687-e303d6ae0dd6'),
(11,11,'Product 11','DRIVE','1WU8V24LzEIJaSoOQHrwjqae0jQrNroE7','https://drive.google.com/file/d/1WU8V24LzEIJaSoOQHrwjqae0jQrNroE7/view?usp=drive_link'),
(12,12,'Product 12','DRIVE','1cJBaxqK_zwKBi05fVVST1N6efws8BoG1','https://drive.google.com/file/d/1cJBaxqK_zwKBi05fVVST1N6efws8BoG1/view?usp=drive_link'),
(13,13,'Product 13','DRIVE','1inzeJqL6csen7yNo9FoTxbeWz78x5XW0','https://drive.google.com/file/d/1inzeJqL6csen7yNo9FoTxbeWz78x5XW0/view?usp=drive_link')
ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,source_type=EXCLUDED.source_type,source_ref=EXCLUDED.source_ref,share_url=EXCLUDED.share_url;
