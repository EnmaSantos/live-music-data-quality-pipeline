CREATE TABLE IF NOT EXISTS ingestion_runs (
    id UUID PRIMARY KEY,
    source_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_loaded INTEGER NOT NULL DEFAULT 0,
    issue_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    CONSTRAINT ingestion_runs_status_check
        CHECK (status IN ('running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS live_music_events (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_event_id TEXT,
    source_artist_id TEXT,
    artist_name_raw TEXT,
    artist_name_clean TEXT,
    artist_fingerprint TEXT,
    genre_clean TEXT,
    source_venue_id TEXT,
    venue_name_raw TEXT,
    venue_name_clean TEXT,
    venue_fingerprint TEXT,
    venue_capacity INTEGER,
    address TEXT,
    city_clean TEXT,
    state_clean TEXT,
    country_clean TEXT,
    market_clean TEXT,
    dma_code TEXT,
    event_name_raw TEXT,
    event_name_clean TEXT,
    event_fingerprint TEXT,
    event_date DATE,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    ticket_demand_score NUMERIC(8, 2),
    airplay_spins INTEGER,
    quality_score INTEGER NOT NULL DEFAULT 100,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT quality_score_range CHECK (quality_score BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    event_fingerprint TEXT,
    entity_type TEXT NOT NULL,
    entity_key TEXT,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    field_name TEXT,
    raw_value TEXT,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT data_quality_issues_entity_type_check
        CHECK (entity_type IN ('event', 'artist', 'venue', 'market')),
    CONSTRAINT data_quality_issues_severity_check
        CHECK (severity IN ('critical', 'error', 'warning', 'info'))
);

CREATE INDEX IF NOT EXISTS idx_live_music_events_run_id
    ON live_music_events(run_id);

CREATE INDEX IF NOT EXISTS idx_live_music_events_source
    ON live_music_events(source);

CREATE INDEX IF NOT EXISTS idx_live_music_events_artist_fingerprint
    ON live_music_events(artist_fingerprint);

CREATE INDEX IF NOT EXISTS idx_live_music_events_venue_fingerprint
    ON live_music_events(venue_fingerprint);

CREATE INDEX IF NOT EXISTS idx_live_music_events_market
    ON live_music_events(market_clean, state_clean);

CREATE INDEX IF NOT EXISTS idx_data_quality_issues_run_id
    ON data_quality_issues(run_id);

CREATE INDEX IF NOT EXISTS idx_data_quality_issues_type
    ON data_quality_issues(issue_type, severity);
