from __future__ import annotations

import argparse
import os
import socket
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.engine import evaluate_records
from app.core.profiles import get_profile
from app.db import get_engine
from app.referee.service import (
    batched,
    expire_details,
    map_record,
    retry_available_at,
    stable_json,
)


def worker_id() -> str:
    return os.getenv("WORKER_ID", f"{socket.gethostname()}-{os.getpid()}")


def claim_run(engine: Engine, identity: str) -> dict[str, Any] | None:
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                WITH candidate AS (
                    SELECT id
                    FROM referee_quality_runs
                    WHERE (
                        status IN ('queued', 'retry_wait')
                        AND available_at <= NOW()
                    ) OR (
                        status = 'running'
                        AND lease_expires_at <= NOW()
                    )
                    ORDER BY available_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE referee_quality_runs AS run
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW()),
                    leased_at = NOW(),
                    lease_expires_at = NOW() + INTERVAL '5 minutes',
                    leased_by = :worker_id,
                    attempt_count = attempt_count + 1,
                    last_error = NULL
                FROM candidate
                WHERE run.id = candidate.id
                RETURNING run.*
                """
                ),
                {"worker_id": identity},
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


def renew_lease(engine: Engine, run_id: str, identity: str, processed: int) -> None:
    with engine.begin() as connection:
        updated = connection.execute(
            text(
                """
                UPDATE referee_quality_runs
                SET lease_expires_at = NOW() + INTERVAL '5 minutes',
                    records_processed = :processed
                WHERE id = :run_id AND leased_by = :worker_id AND status = 'running'
                """
            ),
            {"run_id": run_id, "worker_id": identity, "processed": processed},
        ).rowcount
    if updated != 1:
        raise RuntimeError("Quality-run lease was lost while processing.")


def _load_input(
    engine: Engine, run: dict[str, Any]
) -> tuple[list[int], list[str], list[dict[str, Any]]]:
    with engine.connect() as connection:
        dataset = (
            connection.execute(
                text(
                    """
                SELECT column_mapping
                FROM referee_datasets
                WHERE id = :dataset_id
                """
                ),
                {"dataset_id": str(run["dataset_id"])},
            )
            .mappings()
            .one()
        )
        rows = connection.execution_options(stream_results=True).execute(
            text(
                """
                SELECT id, external_record_id, raw_payload
                FROM referee_raw_records
                WHERE dataset_id = :dataset_id
                ORDER BY ordinal
                """
            ),
            {"dataset_id": str(run["dataset_id"])},
        )
        raw_ids: list[int] = []
        external_ids: list[str] = []
        records: list[dict[str, Any]] = []
        column_mapping = dict(dataset["column_mapping"] or {})
        for row in rows.mappings():
            raw_ids.append(int(row["id"]))
            external_ids.append(str(row["external_record_id"]))
            records.append(map_record(dict(row["raw_payload"]), column_mapping))
    return raw_ids, external_ids, records


def _persist_results(
    engine: Engine,
    run_id: str,
    identity: str,
    raw_ids: list[int],
    evaluations: list[dict[str, Any]],
) -> None:
    processed = 0
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM referee_record_results WHERE run_id = :run_id"),
            {"run_id": run_id},
        )

    paired = list(zip(raw_ids, evaluations))
    for group in batched(paired, 1000):
        result_parameters = [
            {
                "run_id": run_id,
                "raw_record_id": raw_id,
                "external_record_id": evaluation["external_record_id"],
                "score": evaluation["score"],
                "classification": evaluation["classification"],
                "warning_count": evaluation["warning_count"],
                "error_count": evaluation["error_count"],
                "issues": stable_json(evaluation["issues"]),
            }
            for raw_id, evaluation in group
        ]
        external_ids = [parameter["external_record_id"] for parameter in result_parameters]
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO referee_record_results (
                        run_id, raw_record_id, external_record_id, score, classification,
                        warning_count, error_count, issues
                    )
                    VALUES (
                        :run_id, :raw_record_id, :external_record_id, :score, :classification,
                        :warning_count, :error_count, CAST(:issues AS JSONB)
                    )
                    """
                ),
                result_parameters,
            )
            result_ids = {
                row["external_record_id"]: int(row["id"])
                for row in connection.execute(
                    text(
                        """
                        SELECT id, external_record_id
                        FROM referee_record_results
                        WHERE run_id = :run_id
                          AND external_record_id = ANY(:external_ids)
                        """
                    ),
                    {"run_id": run_id, "external_ids": external_ids},
                ).mappings()
            }
            issue_parameters = []
            for _, evaluation in group:
                for issue in evaluation["issues"]:
                    issue_parameters.append(
                        {
                            "run_id": run_id,
                            "record_result_id": result_ids[evaluation["external_record_id"]],
                            "external_record_id": evaluation["external_record_id"],
                            "rule_id": issue["rule_id"],
                            "dimension": issue["dimension"],
                            "severity": issue["severity"],
                            "action": issue["action"],
                            "field_name": issue["field_name"],
                            "message": issue["message"],
                            "recommendation": issue["recommendation"],
                        }
                    )
            if issue_parameters:
                connection.execute(
                    text(
                        """
                        INSERT INTO referee_quality_issues (
                            run_id, record_result_id, external_record_id, rule_id,
                            dimension, severity, action, field_name, message, recommendation
                        )
                        VALUES (
                            :run_id, :record_result_id, :external_record_id, :rule_id,
                            :dimension, :severity, :action, :field_name, :message, :recommendation
                        )
                        """
                    ),
                    issue_parameters,
                )
        processed += len(group)
        renew_lease(engine, run_id, identity, processed)


def complete_run(engine: Engine, run: dict[str, Any], identity: str) -> None:
    run_id = str(run["id"])
    profile = get_profile(str(run["profile_key"]), str(run["profile_version"]))
    raw_ids, external_ids, records = _load_input(engine, run)
    evaluation = evaluate_records(records, profile, external_ids)
    record_dicts = [record.to_dict() for record in evaluation.records]
    _persist_results(engine, run_id, identity, raw_ids, record_dicts)
    summary = evaluation.summary_dict()
    counts = summary["classification_counts"]
    with engine.begin() as connection:
        updated = connection.execute(
            text(
                """
                UPDATE referee_quality_runs
                SET status = 'completed', records_processed = records_total,
                    accepted_count = :accepted, quarantined_count = :quarantined,
                    rejected_count = :rejected, overall_score = :overall_score,
                    verdict = :verdict,
                    dimension_scores = CAST(:dimension_scores AS JSONB),
                    classification_counts = CAST(:classification_counts AS JSONB),
                    use_case_eligibility = CAST(:use_case_eligibility AS JSONB),
                    blocked_use_cases = CAST(:blocked_use_cases AS JSONB),
                    completed_at = NOW(), lease_expires_at = NULL, leased_by = NULL
                WHERE id = :run_id AND leased_by = :worker_id AND status = 'running'
                """
            ),
            {
                "run_id": run_id,
                "worker_id": identity,
                "accepted": counts["accepted"],
                "quarantined": counts["quarantined"],
                "rejected": counts["rejected"],
                "overall_score": summary["overall_score"],
                "verdict": summary["verdict"],
                "dimension_scores": stable_json(summary["dimension_scores"]),
                "classification_counts": stable_json(counts),
                "use_case_eligibility": stable_json(summary["use_case_eligibility"]),
                "blocked_use_cases": stable_json(summary["blocked_use_cases"]),
            },
        ).rowcount
    if updated != 1:
        raise RuntimeError("Quality-run lease was lost before completion.")


def fail_run(engine: Engine, run: dict[str, Any], identity: str, error: Exception) -> None:
    attempt_count = int(run["attempt_count"])
    max_attempts = int(run["max_attempts"])
    status = "dead_letter" if attempt_count >= max_attempts else "retry_wait"
    available_at = retry_available_at(attempt_count)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE referee_quality_runs
                SET status = :status, available_at = :available_at,
                    lease_expires_at = NULL, leased_by = NULL,
                    last_error = :last_error,
                    completed_at = CASE WHEN :status = 'dead_letter' THEN NOW() ELSE NULL END
                WHERE id = :run_id AND leased_by = :worker_id
                """
            ),
            {
                "run_id": str(run["id"]),
                "worker_id": identity,
                "status": status,
                "available_at": available_at,
                "last_error": str(error)[:4000],
            },
        )


def work_once(engine: Engine, identity: str) -> bool:
    expire_details(engine)
    run = claim_run(engine, identity)
    if not run:
        return False
    try:
        complete_run(engine, run, identity)
    except Exception as exc:
        fail_run(engine, run, identity, exc)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued Data Referee quality runs.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    engine = get_engine()
    identity = worker_id()
    while True:
        worked = work_once(engine, identity)
        if args.once:
            return
        if not worked:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
