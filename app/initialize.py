"""Initialize a hosted database and seed it once with the bundled sample data."""

from pathlib import Path

from sqlalchemy import text

from app.db import get_engine
from app.ingestion.pipeline import load_csv, run_migrations

SAMPLE_CSV = Path(__file__).resolve().parents[1] / "data" / "raw" / "sample_events.csv"
LOCK_ID = 734_620_241


def initialize() -> None:
    engine = get_engine()

    # Both web services can start together. A session-level advisory lock keeps
    # their schema/seed work from racing while still making restarts harmless.
    with engine.connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": LOCK_ID})
        try:
            run_migrations(engine)
            event_count = lock_connection.execute(
                text("SELECT COUNT(*) FROM live_music_events")
            ).scalar_one()
            if event_count == 0:
                load_csv(SAMPLE_CSV, source_name="sample_events")
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": LOCK_ID}
            )


if __name__ == "__main__":
    initialize()
