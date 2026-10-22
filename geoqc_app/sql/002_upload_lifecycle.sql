-- Preserve original rows and metadata; expired sessions are closed by the sweeper.
ALTER TABLE upload_sessions DROP CONSTRAINT upload_sessions_state_check;
ALTER TABLE upload_sessions ADD CONSTRAINT upload_sessions_state_check
    CHECK(state IN ('UPLOADING','VERIFIED','REJECTED','EXPIRED','CANCELLED'));
ALTER TABLE upload_sessions ADD COLUMN expires_at timestamptz;
UPDATE upload_sessions SET expires_at=created_at+interval '24 hours';
ALTER TABLE upload_sessions ALTER COLUMN expires_at SET NOT NULL;
ALTER TABLE upload_sessions ALTER COLUMN expires_at SET DEFAULT (clock_timestamp()+interval '24 hours');
ALTER TABLE upload_sessions ADD COLUMN closed_at timestamptz;
ALTER TABLE upload_sessions ADD COLUMN cancellation_reason text;
CREATE INDEX expiring_uploads ON upload_sessions(expires_at,id) WHERE state='UPLOADING';
