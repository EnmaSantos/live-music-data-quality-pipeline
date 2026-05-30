from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings


@lru_cache
def get_engine(database_url: Optional[str] = None) -> Engine:
    url = database_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True, future=True)


def ping_database(engine: Optional[Engine] = None) -> bool:
    active_engine = engine or get_engine()
    with active_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def fetch_all(
    query: str,
    params: Optional[dict[str, Any]] = None,
    engine: Optional[Engine] = None,
) -> list[dict[str, Any]]:
    active_engine = engine or get_engine()
    with active_engine.connect() as connection:
        result = connection.execute(text(query), params or {})
        return [dict(row) for row in result.mappings().all()]


def fetch_one(
    query: str,
    params: Optional[dict[str, Any]] = None,
    engine: Optional[Engine] = None,
) -> dict[str, Any]:
    rows = fetch_all(query, params=params, engine=engine)
    return rows[0] if rows else {}
