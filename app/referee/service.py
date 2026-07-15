from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.models import ProfileDefinition
from app.core.profiles import get_profile, list_profiles


class RefereeConflictError(RuntimeError):
    pass


class RefereeNotFoundError(RuntimeError):
    pass


class RefereeStateError(RuntimeError):
    pass


class RefereeExpiredError(RuntimeError):
    pass


@dataclass(frozen=True)
class IdempotencyReplay:
    status_code: int
    body: dict[str, Any]


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def body_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def seed_profiles(engine: Engine) -> None:
    with engine.begin() as connection:
        for profile in list_profiles():
            connection.execute(
                text(
                    """
                    INSERT INTO quality_profiles (
                        profile_key, profile_version, name, description, status,
                        definition, published_at
                    )
                    VALUES (
                        :profile_key, :profile_version, :name, :description, :status,
                        CAST(:definition AS JSONB), NOW()
                    )
                    ON CONFLICT (profile_key, profile_version) DO NOTHING
                    """
                ),
                {
                    "profile_key": profile.profile_key,
                    "profile_version": profile.profile_version,
                    "name": profile.name,
                    "description": profile.description,
                    "status": profile.status,
                    "definition": stable_json(profile.to_dict()),
                },
            )


def check_idempotency(
    engine: Engine,
    client_id: str,
    method: str,
    path: str,
    key: str,
    request_hash: str,
) -> IdempotencyReplay | None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM referee_idempotency_keys WHERE expires_at <= NOW()"))
        row = (
            connection.execute(
                text(
                    """
                SELECT request_body_hash, response_status, response_body
                FROM referee_idempotency_keys
                WHERE client_id = :client_id
                  AND http_method = :method
                  AND request_path = :path
                  AND idempotency_key = :key
                """
                ),
                {"client_id": client_id, "method": method, "path": path, "key": key},
            )
            .mappings()
            .first()
        )
    if not row:
        return None
    if row["request_body_hash"] != request_hash:
        raise RefereeConflictError("Idempotency key was already used with a different payload.")
    return IdempotencyReplay(int(row["response_status"]), dict(row["response_body"]))


def store_idempotency(
    engine: Engine,
    client_id: str,
    method: str,
    path: str,
    key: str,
    request_hash: str,
    status_code: int,
    response_body: dict[str, Any],
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO referee_idempotency_keys (
                    client_id, http_method, request_path, idempotency_key,
                    request_body_hash, response_status, response_body, expires_at
                )
                VALUES (
                    :client_id, :method, :path, :key,
                    :request_hash, :status_code, CAST(:response_body AS JSONB),
                    NOW() + INTERVAL '7 days'
                )
                ON CONFLICT (client_id, http_method, request_path, idempotency_key)
                DO NOTHING
                """
            ),
            {
                "client_id": client_id,
                "method": method,
                "path": path,
                "key": key,
                "request_hash": request_hash,
                "status_code": status_code,
                "response_body": stable_json(response_body),
            },
        )


def create_dataset(
    engine: Engine,
    client_id: str,
    name: str,
    source_type: str,
    retention_hours: int,
    column_mapping: dict[str, str],
) -> dict[str, Any]:
    dataset_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO referee_datasets (
                    id, client_id, name, source_type, retention_hours, column_mapping
                )
                VALUES (
                    :id, :client_id, :name, :source_type, :retention_hours,
                    CAST(:column_mapping AS JSONB)
                )
                """
            ),
            {
                "id": str(dataset_id),
                "client_id": client_id,
                "name": name,
                "source_type": source_type,
                "retention_hours": retention_hours,
                "column_mapping": stable_json(column_mapping),
            },
        )
    return {"id": str(dataset_id), "status": "created", "name": name}


def _dataset_for_update(connection: Any, dataset_id: str, client_id: str) -> dict[str, Any]:
    row = (
        connection.execute(
            text(
                """
            SELECT * FROM referee_datasets
            WHERE id = :dataset_id AND client_id = :client_id
            FOR UPDATE
            """
            ),
            {"dataset_id": dataset_id, "client_id": client_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise RefereeNotFoundError("Dataset not found.")
    return dict(row)


def append_record_batch(
    engine: Engine,
    client_id: str,
    dataset_id: str,
    batch_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(records) > 1000:
        raise ValueError("Record batches are limited to 1,000 records.")
    batch_hash = body_hash(records)
    external_ids = [str(record["external_record_id"]) for record in records]
    if len(external_ids) != len(set(external_ids)):
        raise RefereeConflictError("external_record_id values must be unique in a dataset.")

    with engine.begin() as connection:
        dataset = _dataset_for_update(connection, dataset_id, client_id)
        if dataset["status"] not in {"created", "receiving_records"}:
            raise RefereeStateError("Records cannot be appended after a dataset is sealed.")
        prior = (
            connection.execute(
                text(
                    """
                SELECT body_hash, response_body
                FROM referee_record_batches
                WHERE dataset_id = :dataset_id AND batch_id = :batch_id
                """
                ),
                {"dataset_id": dataset_id, "batch_id": batch_id},
            )
            .mappings()
            .first()
        )
        if prior:
            if prior["body_hash"] != batch_hash:
                raise RefereeConflictError("batch_id was already used with different records.")
            return dict(prior["response_body"])

        existing_ids = (
            connection.execute(
                text(
                    """
                SELECT external_record_id
                FROM referee_raw_records
                WHERE dataset_id = :dataset_id
                  AND external_record_id = ANY(:external_ids)
                """
                ),
                {"dataset_id": dataset_id, "external_ids": external_ids},
            )
            .scalars()
            .all()
        )
        if existing_ids:
            raise RefereeConflictError(
                f"Duplicate external_record_id values: {', '.join(existing_ids[:5])}"
            )
        start_ordinal = int(
            connection.execute(
                text(
                    "SELECT COALESCE(MAX(ordinal), 0) FROM referee_raw_records "
                    "WHERE dataset_id = :dataset_id"
                ),
                {"dataset_id": dataset_id},
            ).scalar_one()
        )
        parameters = [
            {
                "dataset_id": dataset_id,
                "ordinal": start_ordinal + index,
                "batch_id": batch_id,
                "external_record_id": str(record["external_record_id"]),
                "raw_payload": stable_json(record.get("payload", {})),
            }
            for index, record in enumerate(records, start=1)
        ]
        if parameters:
            connection.execute(
                text(
                    """
                    INSERT INTO referee_raw_records (
                        dataset_id, ordinal, batch_id, external_record_id, raw_payload
                    )
                    VALUES (
                        :dataset_id, :ordinal, :batch_id, :external_record_id,
                        CAST(:raw_payload AS JSONB)
                    )
                    """
                ),
                parameters,
            )
        new_total = start_ordinal + len(records)
        response = {
            "dataset_id": dataset_id,
            "batch_id": batch_id,
            "records_appended": len(records),
            "records_total": new_total,
            "status": "receiving_records",
        }
        connection.execute(
            text(
                """
                INSERT INTO referee_record_batches (
                    dataset_id, batch_id, body_hash, record_count, response_body
                )
                VALUES (
                    :dataset_id, :batch_id, :body_hash, :record_count,
                    CAST(:response_body AS JSONB)
                )
                """
            ),
            {
                "dataset_id": dataset_id,
                "batch_id": batch_id,
                "body_hash": batch_hash,
                "record_count": len(records),
                "response_body": stable_json(response),
            },
        )
        connection.execute(
            text(
                """
                UPDATE referee_datasets
                SET status = 'receiving_records', input_record_count = :total, updated_at = NOW()
                WHERE id = :dataset_id
                """
            ),
            {"dataset_id": dataset_id, "total": new_total},
        )
    return response


def _input_hash(connection: Any, dataset_id: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    result = connection.execute(
        text(
            """
            SELECT external_record_id, raw_payload
            FROM referee_raw_records
            WHERE dataset_id = :dataset_id
            ORDER BY ordinal
            """
        ),
        {"dataset_id": dataset_id},
    )
    for row in result.mappings():
        digest.update(str(row["external_record_id"]).encode())
        digest.update(b"\0")
        digest.update(stable_json(row["raw_payload"]).encode())
        digest.update(b"\n")
        count += 1
    result.close()
    return digest.hexdigest(), count


def create_quality_run(
    engine: Engine,
    client_id: str,
    dataset_id: str,
    profile_key: str,
    profile_version: str | None,
    retry_of: str | None = None,
) -> dict[str, Any]:
    profile: ProfileDefinition = get_profile(profile_key, profile_version)
    run_id = uuid.uuid4()
    with engine.begin() as connection:
        dataset = _dataset_for_update(connection, dataset_id, client_id)
        if dataset["status"] not in {"created", "receiving_records", "sealed"}:
            raise RefereeStateError("Expired datasets cannot be evaluated.")
        if dataset["status"] == "sealed" and retry_of is None:
            raise RefereeStateError("A sealed dataset can only be used for an explicit retry.")
        calculated_hash, record_count = _input_hash(connection, dataset_id)
        input_hash = dataset["input_hash"] or calculated_hash
        if dataset["input_hash"] and dataset["input_hash"] != calculated_hash:
            raise RefereeStateError("Sealed dataset content does not match its input hash.")
        profile_snapshot = profile.to_dict()
        evaluation_hash = body_hash(
            {
                "input_hash": input_hash,
                "profile": profile_snapshot,
                "column_mapping": dataset["column_mapping"],
            }
        )
        connection.execute(
            text(
                """
                UPDATE referee_datasets
                SET status = 'sealed', input_hash = :input_hash,
                    input_record_count = :record_count, sealed_at = COALESCE(sealed_at, NOW()),
                    details_expire_at = COALESCE(
                        details_expire_at,
                        NOW() + make_interval(hours => retention_hours)
                    ), updated_at = NOW()
                WHERE id = :dataset_id
                """
            ),
            {
                "dataset_id": dataset_id,
                "input_hash": input_hash,
                "record_count": record_count,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO referee_quality_runs (
                    id, dataset_id, client_id, profile_key, profile_version,
                    profile_snapshot, retry_of, records_total, input_hash, evaluation_hash
                )
                VALUES (
                    :id, :dataset_id, :client_id, :profile_key, :profile_version,
                    CAST(:profile_snapshot AS JSONB), :retry_of, :records_total,
                    :input_hash, :evaluation_hash
                )
                """
            ),
            {
                "id": str(run_id),
                "dataset_id": dataset_id,
                "client_id": client_id,
                "profile_key": profile.profile_key,
                "profile_version": profile.profile_version,
                "profile_snapshot": stable_json(profile_snapshot),
                "retry_of": retry_of,
                "records_total": record_count,
                "input_hash": input_hash,
                "evaluation_hash": evaluation_hash,
            },
        )
    return {
        "id": str(run_id),
        "dataset_id": dataset_id,
        "status": "queued",
        "records_total": record_count,
        "profile_key": profile.profile_key,
        "profile_version": profile.profile_version,
    }


def get_run(engine: Engine, client_id: str, run_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT id::text AS id, dataset_id::text AS dataset_id, status,
                       records_total, records_processed, profile_key, profile_version,
                       created_at, started_at, completed_at, last_error
                FROM referee_quality_runs
                WHERE id = :run_id AND client_id = :client_id
                """
                ),
                {"run_id": run_id, "client_id": client_id},
            )
            .mappings()
            .first()
        )
    if not row:
        raise RefereeNotFoundError("Quality run not found.")
    result = dict(row)
    total = int(result["records_total"] or 0)
    processed = int(result["records_processed"] or 0)
    result["progress"] = (
        1.0
        if total == 0 and result["status"] == "completed"
        else round(processed / max(total, 1), 4)
    )
    return result


def get_summary(engine: Engine, client_id: str, run_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT id::text AS quality_run_id, profile_key, profile_version,
                       records_total AS input_record_count, input_hash, evaluation_hash,
                       overall_score::float AS overall_score, verdict,
                       dimension_scores, classification_counts,
                       blocked_use_cases, use_case_eligibility, created_at, completed_at
                FROM referee_quality_runs
                WHERE id = :run_id AND client_id = :client_id
                """
                ),
                {"run_id": run_id, "client_id": client_id},
            )
            .mappings()
            .first()
        )
    if not row:
        raise RefereeNotFoundError("Quality run not found.")
    return dict(row)


def _assert_details_available(connection: Any, run_id: str, client_id: str) -> None:
    row = connection.execute(
        text(
            """
            SELECT d.status
            FROM referee_quality_runs r
            JOIN referee_datasets d ON d.id = r.dataset_id
            WHERE r.id = :run_id AND r.client_id = :client_id
            """
        ),
        {"run_id": run_id, "client_id": client_id},
    ).first()
    if not row:
        raise RefereeNotFoundError("Quality run not found.")
    if row[0] == "expired":
        raise RefereeExpiredError("Detailed quality results have expired.")


def encode_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode()).decode().rstrip("=")


def decode_cursor(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor.") from exc


def list_record_results(
    engine: Engine,
    client_id: str,
    run_id: str,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    after_id = decode_cursor(cursor)
    with engine.connect() as connection:
        _assert_details_available(connection, run_id, client_id)
        rows = (
            connection.execute(
                text(
                    """
                SELECT id, external_record_id, score, classification,
                       warning_count, error_count, issues
                FROM referee_record_results
                WHERE run_id = :run_id AND id > :after_id
                ORDER BY id
                LIMIT :limit
                """
                ),
                {"run_id": run_id, "after_id": after_id, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [dict(row) for row in page],
        "next_cursor": encode_cursor(int(page[-1]["id"])) if has_more and page else None,
    }


def list_issues(
    engine: Engine,
    client_id: str,
    run_id: str,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    after_id = decode_cursor(cursor)
    with engine.connect() as connection:
        _assert_details_available(connection, run_id, client_id)
        rows = (
            connection.execute(
                text(
                    """
                SELECT id, external_record_id, rule_id, dimension, severity, action,
                       field_name, message, recommendation
                FROM referee_quality_issues
                WHERE run_id = :run_id AND id > :after_id
                ORDER BY id
                LIMIT :limit
                """
                ),
                {"run_id": run_id, "after_id": after_id, "limit": limit + 1},
            )
            .mappings()
            .all()
        )
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [dict(row) for row in page],
        "next_cursor": encode_cursor(int(page[-1]["id"])) if has_more and page else None,
    }


def retry_run(engine: Engine, client_id: str, run_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        prior = (
            connection.execute(
                text(
                    """
                SELECT dataset_id::text AS dataset_id, profile_key, profile_version, status
                FROM referee_quality_runs
                WHERE id = :run_id AND client_id = :client_id
                """
                ),
                {"run_id": run_id, "client_id": client_id},
            )
            .mappings()
            .first()
        )
    if not prior:
        raise RefereeNotFoundError("Quality run not found.")
    if prior["status"] not in {"failed", "dead_letter"}:
        raise RefereeStateError("Only terminal failed runs can be retried manually.")
    return create_quality_run(
        engine,
        client_id,
        prior["dataset_id"],
        prior["profile_key"],
        prior["profile_version"],
        retry_of=run_id,
    )


def expire_details(engine: Engine) -> int:
    with engine.begin() as connection:
        dataset_ids = (
            connection.execute(
                text(
                    """
                SELECT id::text FROM referee_datasets
                WHERE status = 'sealed' AND details_expire_at <= NOW()
                FOR UPDATE SKIP LOCKED
                """
                )
            )
            .scalars()
            .all()
        )
        if not dataset_ids:
            return 0
        connection.execute(
            text("DELETE FROM referee_raw_records WHERE dataset_id = ANY(:dataset_ids)"),
            {"dataset_ids": dataset_ids},
        )
        connection.execute(
            text(
                """
                UPDATE referee_datasets
                SET status = 'expired', updated_at = NOW()
                WHERE id = ANY(:dataset_ids)
                """
            ),
            {"dataset_ids": dataset_ids},
        )
        return len(dataset_ids)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retry_available_at(attempt_count: int) -> datetime:
    delay_seconds = min(30 * (2 ** max(attempt_count - 1, 0)), 1800)
    return utc_now() + timedelta(seconds=delay_seconds)


def map_record(payload: dict[str, Any], column_mapping: dict[str, str]) -> dict[str, Any]:
    if not column_mapping:
        return payload
    mapped = dict(payload)
    for profile_field, source_column in column_mapping.items():
        mapped[profile_field] = payload.get(source_column)
    return mapped


def batched(values: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
