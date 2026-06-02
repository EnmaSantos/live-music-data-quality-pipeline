from fastapi import FastAPI, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import fetch_all, fetch_one, ping_database

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Data quality API for cleaned live-music events, venues, artists, and markets.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        ping_database()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=f"Database unreachable: {exc}") from exc

    return {"status": "ok", "database": "reachable"}


@app.get("/data-quality-report")
def data_quality_report(
    limit: int = Query(default=settings.api_default_limit, ge=1, le=500),
) -> dict[str, object]:
    try:
        summary = fetch_one(
            """
            SELECT
                COUNT(*)::integer AS event_records,
                COUNT(DISTINCT artist_fingerprint)::integer AS unique_artists,
                COUNT(DISTINCT venue_fingerprint)::integer AS unique_venues,
                COALESCE(ROUND(AVG(quality_score)::numeric, 2), 0) AS avg_quality_score
            FROM live_music_events
            """
        )
        score_by_source = fetch_all(
            """
            SELECT *
            FROM vw_data_quality_score_by_source
            ORDER BY avg_quality_score ASC, issue_count DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
        top_issues = fetch_all(
            """
            SELECT issue_type, severity, COUNT(*)::integer AS issue_count
            FROM data_quality_issues
            GROUP BY issue_type, severity
            ORDER BY issue_count DESC, issue_type
            LIMIT :limit
            """,
            {"limit": limit},
        )
        recent_runs = fetch_all(
            """
            SELECT
                id::text AS id,
                source_name,
                started_at,
                finished_at,
                records_seen,
                records_loaded,
                issue_count,
                status
            FROM ingestion_runs
            ORDER BY started_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Could not build report: {exc}") from exc

    return {
        "summary": summary,
        "score_by_source": score_by_source,
        "top_issues": top_issues,
        "recent_ingestion_runs": recent_runs,
    }


@app.get("/venues/issues")
def venue_issues(
    limit: int = Query(default=settings.api_default_limit, ge=1, le=500),
) -> dict[str, object]:
    try:
        rows = fetch_all(
            """
            SELECT *
            FROM vw_venues_missing_metadata
            ORDER BY event_count DESC, venue_name
            LIMIT :limit
            """,
            {"limit": limit},
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Could not fetch venue issues: {exc}") from exc

    return {"count": len(rows), "venues": rows}


@app.get("/artists/duplicates")
def artist_duplicates(
    limit: int = Query(default=settings.api_default_limit, ge=1, le=500),
) -> dict[str, object]:
    try:
        rows = fetch_all(
            """
            SELECT *
            FROM vw_duplicate_artist_candidates
            ORDER BY duplicate_record_count DESC, event_count DESC, canonical_artist_name
            LIMIT :limit
            """,
            {"limit": limit},
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not fetch duplicate artists: {exc}",
        ) from exc

    return {"count": len(rows), "artists": rows}


@app.get("/artists/search-report")
def artist_search_report(
    limit: int = Query(default=settings.api_default_limit, ge=1, le=500),
) -> dict[str, object]:
    try:
        rows = fetch_all(
            """
            SELECT *
            FROM vw_artist_search_quality
            ORDER BY loaded_events DESC, searched_artist
            LIMIT :limit
            """,
            {"limit": limit},
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not fetch artist search report: {exc}",
        ) from exc

    return {"count": len(rows), "artist_searches": rows}


@app.get("/markets/top")
def top_markets(
    limit: int = Query(default=settings.api_default_limit, ge=1, le=500),
) -> dict[str, object]:
    try:
        rows = fetch_all(
            """
            SELECT *
            FROM vw_top_markets_by_event_count
            ORDER BY event_count DESC, market
            LIMIT :limit
            """,
            {"limit": limit},
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Could not fetch top markets: {exc}") from exc

    return {"count": len(rows), "markets": rows}
