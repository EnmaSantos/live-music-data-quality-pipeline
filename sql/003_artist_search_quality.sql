CREATE OR REPLACE VIEW vw_artist_search_quality AS
WITH artist_runs AS (
    SELECT
        source_name AS source,
        INITCAP(REPLACE(REPLACE(source_name, 'ticketmaster_artist_', ''), '_', ' '))
            AS searched_artist,
        MAX(started_at) AS last_pulled_at,
        SUM(records_seen)::integer AS api_rows,
        SUM(records_loaded)::integer AS records_loaded,
        SUM(issue_count)::integer AS run_issue_count
    FROM ingestion_runs
    WHERE source_name LIKE 'ticketmaster_artist_%'
    GROUP BY source_name
),
event_summary AS (
    SELECT
        source,
        COUNT(*)::integer AS loaded_events,
        COUNT(DISTINCT artist_fingerprint)::integer AS unique_artists,
        COUNT(DISTINCT venue_fingerprint)::integer AS unique_venues,
        MIN(event_date) AS first_event_date,
        MAX(event_date) AS last_event_date,
        ROUND(AVG(quality_score)::numeric, 2) AS avg_quality_score
    FROM live_music_events
    WHERE source LIKE 'ticketmaster_artist_%'
    GROUP BY source
),
issue_summary AS (
    SELECT
        source,
        COUNT(*)::integer AS issue_count,
        COUNT(*) FILTER (WHERE severity = 'error')::integer AS error_count,
        COUNT(*) FILTER (WHERE severity = 'warning')::integer AS warning_count
    FROM data_quality_issues
    WHERE source LIKE 'ticketmaster_artist_%'
    GROUP BY source
),
top_artist AS (
    SELECT source, artist_name_clean AS top_returned_artist, event_count
    FROM (
        SELECT
            source,
            artist_name_clean,
            COUNT(*)::integer AS event_count,
            ROW_NUMBER() OVER (
                PARTITION BY source
                ORDER BY COUNT(*) DESC, artist_name_clean
            ) AS row_number
        FROM live_music_events
        WHERE source LIKE 'ticketmaster_artist_%'
        GROUP BY source, artist_name_clean
    ) ranked
    WHERE row_number = 1
)
SELECT
    artist_runs.source,
    artist_runs.searched_artist,
    artist_runs.last_pulled_at,
    artist_runs.api_rows,
    COALESCE(event_summary.loaded_events, 0) AS loaded_events,
    COALESCE(event_summary.unique_artists, 0) AS unique_artists,
    COALESCE(event_summary.unique_venues, 0) AS unique_venues,
    event_summary.first_event_date,
    event_summary.last_event_date,
    COALESCE(event_summary.avg_quality_score, 0) AS avg_quality_score,
    COALESCE(issue_summary.issue_count, 0) AS issue_count,
    COALESCE(issue_summary.error_count, 0) AS error_count,
    COALESCE(issue_summary.warning_count, 0) AS warning_count,
    top_artist.top_returned_artist,
    COALESCE(top_artist.event_count, 0) AS top_returned_artist_events
FROM artist_runs
LEFT JOIN event_summary ON event_summary.source = artist_runs.source
LEFT JOIN issue_summary ON issue_summary.source = artist_runs.source
LEFT JOIN top_artist ON top_artist.source = artist_runs.source;
