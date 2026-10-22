CREATE TABLE organizations (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE projects (
    id uuid PRIMARY KEY, organization_id uuid NOT NULL REFERENCES organizations,
    name text NOT NULL
);
CREATE TABLE app_users (id uuid PRIMARY KEY, name text NOT NULL, active boolean NOT NULL DEFAULT true);
CREATE TABLE access_tokens (
    digest text PRIMARY KEY, user_id uuid NOT NULL REFERENCES app_users,
    expires_at timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE memberships (
    project_id uuid NOT NULL REFERENCES projects, user_id uuid NOT NULL REFERENCES app_users,
    roles text[] NOT NULL, PRIMARY KEY(project_id,user_id),
    CHECK (roles <@ ARRAY['FIELD_OPERATOR','OFFICE_REVIEWER','PROJECT_ADMIN']::text[])
);
CREATE TABLE acquisitions (
    id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects, name text NOT NULL,
    created_by uuid NOT NULL REFERENCES app_users, revision_number integer NOT NULL DEFAULT 0,
    current_run_id uuid, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(project_id,id)
);
CREATE TABLE artifacts (
    id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects,
    storage_key text UNIQUE NOT NULL, sha256 text NOT NULL CHECK(length(sha256)=64),
    size_bytes bigint NOT NULL CHECK(size_bytes>=0), kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(project_id,id)
);
CREATE TABLE upload_sessions (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, acquisition_id uuid NOT NULL,
    state text NOT NULL DEFAULT 'UPLOADING' CHECK(state IN ('UPLOADING','VERIFIED','REJECTED')),
    waveform_id uuid, sidecar_id uuid, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(project_id,id),
    FOREIGN KEY(project_id,acquisition_id) REFERENCES acquisitions(project_id,id),
    FOREIGN KEY(project_id,waveform_id) REFERENCES artifacts(project_id,id),
    FOREIGN KEY(project_id,sidecar_id) REFERENCES artifacts(project_id,id)
);
CREATE TABLE acquisition_revisions (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, acquisition_id uuid NOT NULL,
    number integer NOT NULL, uploads jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(project_id,id),
    UNIQUE(acquisition_id,number),
    FOREIGN KEY(project_id,acquisition_id) REFERENCES acquisitions(project_id,id)
);
CREATE TABLE processing_runs (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, acquisition_id uuid NOT NULL, revision_id uuid NOT NULL,
    specification jsonb NOT NULL, state text NOT NULL DEFAULT 'QUEUED',
    attempt integer NOT NULL DEFAULT 0, max_attempts integer NOT NULL,
    token uuid, lease_until timestamptz, available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    error_code text, dossier_id uuid, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(project_id,id),
    CHECK(state IN ('QUEUED','VALIDATING','RUNNING','RETRY_WAIT','SUCCEEDED','FAILED','CANCELLED')),
    FOREIGN KEY(project_id,acquisition_id) REFERENCES acquisitions(project_id,id),
    FOREIGN KEY(project_id,revision_id) REFERENCES acquisition_revisions(project_id,id)
);
ALTER TABLE acquisitions ADD FOREIGN KEY(project_id,current_run_id) REFERENCES processing_runs(project_id,id);
CREATE INDEX claim_runs ON processing_runs(state,available_at,created_at);
CREATE TABLE processing_attempts (
    run_id uuid NOT NULL REFERENCES processing_runs, number integer NOT NULL, token uuid UNIQUE NOT NULL,
    state text NOT NULL, error_code text, started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz, PRIMARY KEY(run_id,number)
);
CREATE TABLE dossiers (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, run_id uuid UNIQUE NOT NULL,
    artifact_id uuid NOT NULL, scientific_digest text NOT NULL, manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(project_id,id),
    FOREIGN KEY(project_id,run_id) REFERENCES processing_runs(project_id,id),
    FOREIGN KEY(project_id,artifact_id) REFERENCES artifacts(project_id,id)
);
ALTER TABLE processing_runs ADD FOREIGN KEY(project_id,dossier_id) REFERENCES dossiers(project_id,id);
CREATE TABLE review_cases (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, dossier_id uuid UNIQUE NOT NULL,
    version bigint NOT NULL DEFAULT 1 CHECK(version>0), state text NOT NULL DEFAULT 'PENDING',
    CHECK(state IN ('PENDING','DECIDED')), UNIQUE(project_id,id),
    FOREIGN KEY(project_id,dossier_id) REFERENCES dossiers(project_id,id)
);
CREATE TABLE review_history (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, review_id uuid NOT NULL,
    version bigint NOT NULL, actor_id uuid NOT NULL REFERENCES app_users,
    action text NOT NULL, content jsonb NOT NULL, decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(review_id,version), FOREIGN KEY(project_id,review_id) REFERENCES review_cases(project_id,id)
);
CREATE TABLE commands (
    actor_id uuid NOT NULL REFERENCES app_users, project_id uuid NOT NULL REFERENCES projects,
    operation text NOT NULL, key text NOT NULL, request_hash text NOT NULL,
    response jsonb NOT NULL, status integer NOT NULL, etag text,
    PRIMARY KEY(actor_id,project_id,operation,key)
);
CREATE TABLE outbox (
    id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES projects, aggregate_id uuid NOT NULL,
    event_type text NOT NULL, payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(), dispatched_at timestamptz
);
CREATE TABLE change_entries (
    project_id uuid NOT NULL REFERENCES projects, sequence bigint NOT NULL, event_id uuid UNIQUE NOT NULL,
    event_type text NOT NULL, payload jsonb NOT NULL, PRIMARY KEY(project_id,sequence)
);
CREATE TABLE project_change_counters (
    project_id uuid PRIMARY KEY REFERENCES projects, sequence bigint NOT NULL DEFAULT 0
);
