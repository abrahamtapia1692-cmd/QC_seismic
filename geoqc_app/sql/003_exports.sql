CREATE TABLE exports (
    id uuid PRIMARY KEY, project_id uuid NOT NULL, dossier_id uuid NOT NULL,
    format text NOT NULL CHECK(format IN ('CSV','HTML','PDF')),
    renderer_reference jsonb NOT NULL,
    state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','RUNNING','READY','FAILED')),
    attempt integer NOT NULL DEFAULT 0 CHECK(attempt>=0), max_attempts integer NOT NULL CHECK(max_attempts>0),
    token uuid, lease_until timestamptz, error_code text, artifact_id uuid, manifest jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(project_id,id),
    CHECK((state='RUNNING')=(token IS NOT NULL)),
    CHECK((state='RUNNING')=(lease_until IS NOT NULL)),
    CHECK((state='READY')=(artifact_id IS NOT NULL)),
    FOREIGN KEY(project_id,dossier_id) REFERENCES dossiers(project_id,id),
    FOREIGN KEY(project_id,artifact_id) REFERENCES artifacts(project_id,id)
);
CREATE INDEX claim_exports ON exports(state,created_at);
CREATE TABLE export_attempts (
    export_id uuid NOT NULL REFERENCES exports, number integer NOT NULL, token uuid UNIQUE NOT NULL,
    state text NOT NULL CHECK(state IN ('ACTIVE','EXPIRED','SUCCEEDED','FAILED')),
    error_code text, started_at timestamptz NOT NULL DEFAULT clock_timestamp(), finished_at timestamptz,
    PRIMARY KEY(export_id,number)
);
