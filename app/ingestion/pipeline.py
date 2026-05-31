from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.db import get_engine
from app.ingestion.normalize import dataframe_for_sql, normalize_frame
from app.ingestion.validation import validate_frame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

EVENT_COLUMNS = [
    "run_id",
    "source",
    "source_event_id",
    "source_artist_id",
    "artist_name_raw",
    "artist_name_clean",
    "artist_fingerprint",
    "genre_clean",
    "source_venue_id",
    "venue_name_raw",
    "venue_name_clean",
    "venue_fingerprint",
    "venue_capacity",
    "address",
    "city_clean",
    "state_clean",
    "country_clean",
    "market_clean",
    "dma_code",
    "event_name_raw",
    "event_name_clean",
    "event_fingerprint",
    "event_date",
    "latitude",
    "longitude",
    "ticket_demand_score",
    "airplay_spins",
    "quality_score",
]

ISSUE_COLUMNS = [
    "run_id",
    "source",
    "event_fingerprint",
    "entity_type",
    "entity_key",
    "issue_type",
    "severity",
    "field_name",
    "raw_value",
    "message",
]


def _execute_sql_script(engine: Engine, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def run_migrations(engine: Engine) -> None:
    for path in sorted(SQL_DIR.glob("*.sql")):
        _execute_sql_script(engine, path)


def reset_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                    data_quality_issues,
                    live_music_events,
                    ingestion_runs
                RESTART IDENTITY CASCADE
                """
            )
        )


def _insert_frame(connection: Any, frame: pd.DataFrame, table_name: str, chunk_size: int) -> int:
    if frame.empty:
        return 0
    sql_frame = dataframe_for_sql(frame)
    dtype = {"run_id": UUID(as_uuid=True)} if "run_id" in sql_frame.columns else None
    sql_frame.to_sql(
        table_name,
        connection,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=chunk_size,
        dtype=dtype,
    )
    return len(sql_frame)


def _record_run_start(engine: Engine, run_id: uuid.UUID, source_name: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ingestion_runs (id, source_name, status)
                VALUES (:id, :source_name, 'running')
                """
            ),
            {"id": str(run_id), "source_name": source_name},
        )


def _record_run_finish(
    engine: Engine,
    run_id: uuid.UUID,
    status: str,
    records_seen: int,
    records_loaded: int,
    issue_count: int,
    error_message: Optional[str] = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE ingestion_runs
                SET
                    finished_at = NOW(),
                    records_seen = :records_seen,
                    records_loaded = :records_loaded,
                    issue_count = :issue_count,
                    status = :status,
                    error_message = :error_message
                WHERE id = :id
                """
            ),
            {
                "id": str(run_id),
                "records_seen": records_seen,
                "records_loaded": records_loaded,
                "issue_count": issue_count,
                "status": status,
                "error_message": error_message,
            },
        )


def _insert_duplicate_candidate_issues(engine: Engine, run_id: uuid.UUID) -> int:
    duplicate_sql = """
        WITH duplicate_artists AS (
            SELECT source, artist_fingerprint, MIN(artist_name_clean) AS artist_name
            FROM live_music_events
            WHERE run_id = :run_id AND artist_fingerprint IS NOT NULL
            GROUP BY source, artist_fingerprint
            HAVING COUNT(DISTINCT source_artist_id) > 1
        ),
        duplicate_venues AS (
            SELECT source, venue_fingerprint, MIN(venue_name_clean) AS venue_name
            FROM live_music_events
            WHERE run_id = :run_id AND venue_fingerprint IS NOT NULL
            GROUP BY source, venue_fingerprint
            HAVING COUNT(DISTINCT source_venue_id) > 1
        ),
        inserted_artists AS (
            INSERT INTO data_quality_issues (
                run_id,
                source,
                event_fingerprint,
                entity_type,
                entity_key,
                issue_type,
                severity,
                field_name,
                raw_value,
                message
            )
            SELECT
                :run_id,
                source,
                NULL,
                'artist',
                artist_fingerprint,
                'duplicate_artist_candidate',
                'warning',
                'artist_fingerprint',
                artist_name,
                'Multiple source artist ids share the same normalized artist fingerprint.'
            FROM duplicate_artists
            RETURNING 1
        ),
        inserted_venues AS (
            INSERT INTO data_quality_issues (
                run_id,
                source,
                event_fingerprint,
                entity_type,
                entity_key,
                issue_type,
                severity,
                field_name,
                raw_value,
                message
            )
            SELECT
                :run_id,
                source,
                NULL,
                'venue',
                venue_fingerprint,
                'duplicate_venue_candidate',
                'warning',
                'venue_fingerprint',
                venue_name,
                'Multiple source venue ids share the same normalized venue fingerprint.'
            FROM duplicate_venues
            RETURNING 1
        )
        SELECT
            (SELECT COUNT(*) FROM inserted_artists)
            + (SELECT COUNT(*) FROM inserted_venues) AS inserted_count
    """
    with engine.begin() as connection:
        result = connection.execute(text(duplicate_sql), {"run_id": str(run_id)})
        return int(result.scalar_one())


def load_csv(
    input_path: Path,
    database_url: Optional[str] = None,
    source_name: Optional[str] = None,
    chunk_size: int = 10000,
    replace: bool = False,
) -> dict[str, Any]:
    engine = get_engine(database_url)
    run_migrations(engine)
    if replace:
        reset_tables(engine)

    resolved_source = source_name or input_path.stem
    run_id = uuid.uuid4()
    _record_run_start(engine, run_id, resolved_source)

    records_seen = 0
    records_loaded = 0
    issue_count = 0
    started = time.perf_counter()

    try:
        for chunk in pd.read_csv(input_path, chunksize=chunk_size):
            records_seen += len(chunk)
            clean_frame = normalize_frame(chunk, source_name=resolved_source)
            issue_frame, quality_scores = validate_frame(clean_frame)
            clean_frame["quality_score"] = quality_scores
            clean_frame["run_id"] = run_id

            if issue_frame.empty:
                issue_frame = pd.DataFrame(columns=ISSUE_COLUMNS)
            else:
                issue_frame["run_id"] = run_id
                issue_frame = issue_frame[ISSUE_COLUMNS]

            event_frame = clean_frame[EVENT_COLUMNS]
            with engine.begin() as connection:
                records_loaded += _insert_frame(
                    connection,
                    event_frame,
                    "live_music_events",
                    chunk_size,
                )
                issue_count += _insert_frame(
                    connection,
                    issue_frame,
                    "data_quality_issues",
                    chunk_size,
                )

        issue_count += _insert_duplicate_candidate_issues(engine, run_id)
        _record_run_finish(
            engine,
            run_id,
            "completed",
            records_seen,
            records_loaded,
            issue_count,
        )
    except Exception as exc:
        _record_run_finish(
            engine,
            run_id,
            "failed",
            records_seen,
            records_loaded,
            issue_count,
            error_message=str(exc),
        )
        raise

    return {
        "run_id": str(run_id),
        "source_name": resolved_source,
        "records_seen": records_seen,
        "records_loaded": records_loaded,
        "issue_count": issue_count,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load and validate live-music CSV data.")
    parser.add_argument("--input", type=Path, required=True, help="Path to CSV file to ingest.")
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--chunk-size", type=int, default=10000)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Truncate existing pipeline tables first.",
    )
    args = parser.parse_args()

    result = load_csv(
        input_path=args.input,
        database_url=args.database_url,
        source_name=args.source_name,
        chunk_size=args.chunk_size,
        replace=args.replace,
    )
    print(result)


if __name__ == "__main__":
    main()
