"""Initialize the Data Referee schema and immutable built-in profiles."""

from sqlalchemy import text

from app.db import get_engine
from app.migrations import run_migrations
from app.referee.service import seed_profiles

LOCK_ID = 734_620_241


def initialize() -> None:
    engine = get_engine()

    # Both web services can start together. A session-level advisory lock keeps
    # their schema/seed work from racing while still making restarts harmless.
    with engine.connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": LOCK_ID})
        try:
            run_migrations(engine)
            seed_profiles(engine)
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": LOCK_ID}
            )


if __name__ == "__main__":
    initialize()
