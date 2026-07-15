from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def run_migrations(engine: Engine) -> None:
    for path in sorted(SQL_DIR.glob("*.sql")):
        with engine.begin() as connection:
            connection.exec_driver_sql(path.read_text(encoding="utf-8"))
