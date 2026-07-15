CREATE TABLE IF NOT EXISTS quality_profiles (
    id BIGSERIAL PRIMARY KEY,
    profile_key TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ,
    CONSTRAINT quality_profiles_status_check
        CHECK (status IN ('draft', 'published', 'retired')),
    CONSTRAINT quality_profiles_key_version_unique
        UNIQUE (profile_key, profile_version)
);

CREATE OR REPLACE FUNCTION protect_published_quality_profile()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.status IN ('published', 'retired') THEN
        RAISE EXCEPTION 'Published or retired profiles cannot be deleted';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status IN ('published', 'retired') THEN
        IF OLD.profile_key IS DISTINCT FROM NEW.profile_key
           OR OLD.profile_version IS DISTINCT FROM NEW.profile_version
           OR OLD.name IS DISTINCT FROM NEW.name
           OR OLD.description IS DISTINCT FROM NEW.description
           OR OLD.definition IS DISTINCT FROM NEW.definition
           OR OLD.published_at IS DISTINCT FROM NEW.published_at THEN
            RAISE EXCEPTION 'Published profile definitions are immutable';
        END IF;
        IF OLD.status = 'retired' OR NEW.status NOT IN ('published', 'retired') THEN
            RAISE EXCEPTION 'Published profiles may only transition to retired';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS quality_profiles_immutable ON quality_profiles;
CREATE TRIGGER quality_profiles_immutable
BEFORE UPDATE OR DELETE ON quality_profiles
FOR EACH ROW EXECUTE FUNCTION protect_published_quality_profile();

CREATE TABLE IF NOT EXISTS referee_datasets (
    id UUID PRIMARY KEY,
    client_id TEXT NOT NULL,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'csv',
    status TEXT NOT NULL DEFAULT 'created',
    retention_hours INTEGER NOT NULL DEFAULT 24,
    column_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_record_count INTEGER NOT NULL DEFAULT 0,
    input_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sealed_at TIMESTAMPTZ,
    details_expire_at TIMESTAMPTZ,
    CONSTRAINT referee_datasets_status_check
        CHECK (status IN ('created', 'receiving_records', 'sealed', 'expired')),
    CONSTRAINT referee_datasets_retention_positive CHECK (retention_hours > 0)
);

CREATE TABLE IF NOT EXISTS referee_record_batches (
    id BIGSERIAL PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES referee_datasets(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    record_count INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referee_record_batches_unique UNIQUE (dataset_id, batch_id)
);

CREATE TABLE IF NOT EXISTS referee_raw_records (
    id BIGSERIAL PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES referee_datasets(id) ON DELETE CASCADE,
    ordinal BIGINT NOT NULL,
    batch_id TEXT NOT NULL,
    external_record_id TEXT NOT NULL,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referee_raw_records_external_unique
        UNIQUE (dataset_id, external_record_id),
    CONSTRAINT referee_raw_records_ordinal_unique
        UNIQUE (dataset_id, ordinal)
);

CREATE TABLE IF NOT EXISTS referee_quality_runs (
    id UUID PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES referee_datasets(id),
    client_id TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    profile_snapshot JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    retry_of UUID REFERENCES referee_quality_runs(id),
    records_total INTEGER NOT NULL DEFAULT 0,
    records_processed INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    quarantined_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    overall_score NUMERIC(6, 2),
    verdict TEXT,
    dimension_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    classification_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    use_case_eligibility JSONB NOT NULL DEFAULT '{}'::jsonb,
    blocked_use_cases JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_hash TEXT NOT NULL,
    evaluation_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    leased_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    leased_by TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    last_error TEXT,
    CONSTRAINT referee_quality_runs_status_check
        CHECK (status IN ('queued', 'running', 'retry_wait', 'completed', 'failed', 'dead_letter'))
);

CREATE TABLE IF NOT EXISTS referee_record_results (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES referee_quality_runs(id) ON DELETE CASCADE,
    raw_record_id BIGINT NOT NULL REFERENCES referee_raw_records(id) ON DELETE CASCADE,
    external_record_id TEXT NOT NULL,
    score INTEGER NOT NULL,
    classification TEXT NOT NULL,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    issues JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referee_record_results_score_range CHECK (score BETWEEN 0 AND 100),
    CONSTRAINT referee_record_results_classification_check
        CHECK (classification IN ('accepted', 'quarantined', 'rejected')),
    CONSTRAINT referee_record_results_unique UNIQUE (run_id, external_record_id)
);

CREATE TABLE IF NOT EXISTS referee_quality_issues (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES referee_quality_runs(id) ON DELETE CASCADE,
    record_result_id BIGINT NOT NULL REFERENCES referee_record_results(id) ON DELETE CASCADE,
    external_record_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    severity TEXT NOT NULL,
    action TEXT NOT NULL,
    field_name TEXT,
    message TEXT NOT NULL,
    recommendation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT referee_quality_issues_severity_check
        CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    CONSTRAINT referee_quality_issues_action_check
        CHECK (action IN ('allow', 'quarantine', 'reject'))
);

CREATE TABLE IF NOT EXISTS referee_idempotency_keys (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL,
    http_method TEXT NOT NULL,
    request_path TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_body_hash TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT referee_idempotency_scope_unique
        UNIQUE (client_id, http_method, request_path, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_referee_datasets_client_created
    ON referee_datasets(client_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_referee_raw_records_dataset_ordinal
    ON referee_raw_records(dataset_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_referee_quality_runs_queue
    ON referee_quality_runs(status, available_at, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_referee_record_results_run_id
    ON referee_record_results(run_id, id);

CREATE INDEX IF NOT EXISTS idx_referee_quality_issues_run_id
    ON referee_quality_issues(run_id, id);

CREATE INDEX IF NOT EXISTS idx_referee_idempotency_expiry
    ON referee_idempotency_keys(expires_at);
