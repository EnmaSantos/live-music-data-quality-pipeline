import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import validate
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import get_engine
from app.initialize import initialize
from app.main import app
from app.referee.service import expire_details
from app.worker import work_once

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run PostgreSQL integration tests.",
)

ROOT = Path(__file__).resolve().parents[1]


def headers(key: str, idempotency: str | None = None) -> dict[str, str]:
    values = {
        "X-Data-Referee-Key": key,
        "X-Data-Referee-Client": "integration-test",
    }
    if idempotency:
        values["Idempotency-Key"] = idempotency
    return values


def test_published_profiles_are_immutable() -> None:
    initialize()
    engine = get_engine()
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE quality_profiles SET definition='{}'::jsonb
                    WHERE profile_key='live-events' AND profile_version='1.0.0'
                    """
                )
            )
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM quality_profiles
                    WHERE profile_key='live-events' AND profile_version='1.0.0'
                    """
                )
            )


def test_sealed_evaluation_idempotency_worker_and_retention() -> None:
    initialize()
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                    referee_idempotency_keys,
                    referee_quality_issues,
                    referee_record_results,
                    referee_quality_runs,
                    referee_raw_records,
                    referee_record_batches,
                    referee_datasets
                RESTART IDENTITY CASCADE
                """
            )
        )

    key = os.getenv("DATA_REFEREE_API_KEY", "local-development-key")
    client = TestClient(app)
    create_payload = {
        "name": "ticketmaster-denver",
        "source_type": "service",
        "retention_hours": 24,
        "column_mapping": {},
    }
    created = client.post(
        "/v1/datasets",
        headers=headers(key, "create-dataset"),
        json=create_payload,
    )
    assert created.status_code == 201
    dataset_id = created.json()["id"]
    replay = client.post(
        "/v1/datasets",
        headers=headers(key, "create-dataset"),
        json=create_payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == dataset_id
    conflict = client.post(
        "/v1/datasets",
        headers=headers(key, "create-dataset"),
        json={**create_payload, "name": "different"},
    )
    assert conflict.status_code == 409

    batch_payload = {
        "batch_id": "ticketmaster-denver-page-1",
        "records": [
            {
                "external_record_id": "tm-123",
                "payload": {
                    "event_id": "tm-123",
                    "event_name": "Ava Stone Live",
                    "event_date": "2026-08-01",
                    "artist_name": "Ava Stone",
                    "venue_name": "Mission Ballroom",
                    "venue_capacity": None,
                    "latitude": 39.7392,
                    "longitude": -104.9903,
                    "market": "Denver, CO",
                },
            }
        ],
    }
    appended = client.post(
        f"/v1/datasets/{dataset_id}/record-batches",
        headers=headers(key, "append-page-1"),
        json=batch_payload,
    )
    assert appended.status_code == 201

    queued = client.post(
        f"/v1/datasets/{dataset_id}/quality-runs",
        headers=headers(key, "queue-run"),
        json={"profile_key": "live-events", "profile_version": "1.0.0"},
    )
    assert queued.status_code == 202
    run_id = queued.json()["id"]
    append_after_seal = client.post(
        f"/v1/datasets/{dataset_id}/record-batches",
        headers=headers(key, "append-after-seal"),
        json={**batch_payload, "batch_id": "late-page"},
    )
    assert append_after_seal.status_code == 409

    assert work_once(engine, "integration-worker") is True
    status = client.get(f"/v1/quality-runs/{run_id}", headers=headers(key)).json()
    assert status["status"] == "completed"
    assert status["progress"] == 1.0
    result = client.get(
        f"/v1/quality-runs/{run_id}/record-results",
        headers=headers(key),
    ).json()["items"][0]
    assert result["classification"] == "accepted"
    assert result["warning_count"] == 1
    summary = client.get(
        f"/v1/quality-runs/{run_id}/summary",
        headers=headers(key),
    ).json()
    validate(
        summary,
        json.loads((ROOT / "contracts" / "quality-run-summary.schema.json").read_text()),
    )
    assert "venue_capacity_analysis" in summary["blocked_use_cases"]

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE referee_datasets SET details_expire_at = NOW() - INTERVAL '1 minute' "
                "WHERE id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )
    assert expire_details(engine) == 1
    expired = client.get(
        f"/v1/quality-runs/{run_id}/record-results",
        headers=headers(key),
    )
    assert expired.status_code == 410
    permanent_summary = client.get(
        f"/v1/quality-runs/{run_id}/summary",
        headers=headers(key),
    )
    assert permanent_summary.status_code == 200
