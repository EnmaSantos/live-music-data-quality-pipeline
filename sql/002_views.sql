CREATE OR REPLACE VIEW vw_top_markets_by_event_count AS
SELECT
    COALESCE(market_clean, 'Unknown') AS market,
    COALESCE(state_clean, 'Unknown') AS state,
    COUNT(*)::integer AS event_count,
    COUNT(DISTINCT artist_fingerprint)::integer AS unique_artist_count,
    COUNT(DISTINCT venue_fingerprint)::integer AS unique_venue_count,
    ROUND(AVG(ticket_demand_score)::numeric, 2) AS avg_ticket_demand_score,
    ROUND(AVG(quality_score)::numeric, 2) AS avg_quality_score
FROM live_music_events
GROUP BY COALESCE(market_clean, 'Unknown'), COALESCE(state_clean, 'Unknown');

CREATE OR REPLACE VIEW vw_venues_missing_metadata AS
SELECT
    venue_fingerprint,
    MIN(venue_name_clean) AS venue_name,
    MIN(city_clean) AS city,
    MIN(state_clean) AS state,
    COUNT(*)::integer AS event_count,
    SUM((venue_capacity IS NULL OR venue_capacity <= 0)::integer)::integer
        AS missing_capacity_events,
    SUM((
        latitude IS NULL
        OR longitude IS NULL
        OR latitude < -90
        OR latitude > 90
        OR longitude < -180
        OR longitude > 180
    )::integer)::integer AS invalid_coordinate_events,
    ROUND(AVG(quality_score)::numeric, 2) AS avg_quality_score
FROM live_music_events
GROUP BY venue_fingerprint
HAVING
    SUM((venue_capacity IS NULL OR venue_capacity <= 0)::integer) > 0
    OR SUM((
        latitude IS NULL
        OR longitude IS NULL
        OR latitude < -90
        OR latitude > 90
        OR longitude < -180
        OR longitude > 180
    )::integer) > 0;

CREATE OR REPLACE VIEW vw_duplicate_artist_candidates AS
SELECT
    artist_fingerprint,
    MIN(artist_name_clean) AS canonical_artist_name,
    COUNT(*)::integer AS event_count,
    COUNT(DISTINCT source_artist_id)::integer AS duplicate_record_count,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT source_artist_id), NULL) AS source_artist_ids,
    ARRAY_AGG(DISTINCT source) AS sources,
    ROUND(AVG(quality_score)::numeric, 2) AS avg_quality_score
FROM live_music_events
WHERE artist_fingerprint IS NOT NULL
GROUP BY artist_fingerprint
HAVING COUNT(DISTINCT source_artist_id) > 1;

CREATE OR REPLACE VIEW vw_duplicate_venue_candidates AS
SELECT
    venue_fingerprint,
    MIN(venue_name_clean) AS canonical_venue_name,
    MIN(city_clean) AS city,
    MIN(state_clean) AS state,
    COUNT(*)::integer AS event_count,
    COUNT(DISTINCT source_venue_id)::integer AS duplicate_record_count,
    ARRAY_REMOVE(ARRAY_AGG(DISTINCT source_venue_id), NULL) AS source_venue_ids,
    ARRAY_AGG(DISTINCT source) AS sources,
    ROUND(AVG(quality_score)::numeric, 2) AS avg_quality_score
FROM live_music_events
WHERE venue_fingerprint IS NOT NULL
GROUP BY venue_fingerprint
HAVING COUNT(DISTINCT source_venue_id) > 1;

CREATE OR REPLACE VIEW vw_data_quality_score_by_source AS
WITH event_scores AS (
    SELECT
        source,
        COUNT(*)::integer AS event_records,
        COUNT(DISTINCT artist_fingerprint)::integer AS unique_artists,
        COUNT(DISTINCT venue_fingerprint)::integer AS unique_venues,
        ROUND(AVG(quality_score)::numeric, 2) AS avg_quality_score
    FROM live_music_events
    GROUP BY source
),
issue_counts AS (
    SELECT
        source,
        COUNT(*)::integer AS issue_count,
        COUNT(*) FILTER (WHERE severity = 'critical')::integer AS critical_issues,
        COUNT(*) FILTER (WHERE severity = 'error')::integer AS error_issues,
        COUNT(*) FILTER (WHERE severity = 'warning')::integer AS warning_issues,
        COUNT(*) FILTER (WHERE severity = 'info')::integer AS info_issues
    FROM data_quality_issues
    GROUP BY source
)
SELECT
    event_scores.source,
    event_scores.event_records,
    event_scores.unique_artists,
    event_scores.unique_venues,
    event_scores.avg_quality_score,
    COALESCE(issue_counts.issue_count, 0) AS issue_count,
    COALESCE(issue_counts.critical_issues, 0) AS critical_issues,
    COALESCE(issue_counts.error_issues, 0) AS error_issues,
    COALESCE(issue_counts.warning_issues, 0) AS warning_issues,
    COALESCE(issue_counts.info_issues, 0) AS info_issues
FROM event_scores
LEFT JOIN issue_counts
    ON event_scores.source = issue_counts.source;
