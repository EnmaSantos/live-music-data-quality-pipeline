from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
from collections.abc import Generator
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import text

from app.api.schemas import DatasetCreate, QualityRunCreate, RecordBatchCreate
from app.config import get_settings
from app.core.profiles import get_profile, list_profiles
from app.core.profiling import profile_records
from app.db import get_engine
from app.referee.service import (
    RefereeConflictError,
    RefereeExpiredError,
    RefereeNotFoundError,
    RefereeStateError,
    append_record_batch,
    body_hash,
    check_idempotency,
    create_dataset,
    create_quality_run,
    get_run,
    get_summary,
    list_issues,
    list_record_results,
    retry_run,
    store_idempotency,
)

router = APIRouter(prefix="/v1", tags=["Data Referee"])


def authenticated_client(
    x_data_referee_key: Annotated[str | None, Header()] = None,
    x_data_referee_client: Annotated[str, Header()] = "public-ui",
) -> str:
    expected = get_settings().data_referee_api_key
    if not x_data_referee_key or not secrets.compare_digest(x_data_referee_key, expected):
        raise HTTPException(status_code=401, detail="A valid Data Referee API key is required.")
    return x_data_referee_client


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RefereeConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, RefereeNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RefereeExpiredError):
        return HTTPException(status_code=410, detail=str(exc))
    if isinstance(exc, RefereeStateError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (KeyError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="The quality request could not be processed.")


def _replay_or_none(
    client_id: str,
    method: str,
    path: str,
    key: str,
    request_hash: str,
) -> JSONResponse | None:
    try:
        replay = check_idempotency(get_engine(), client_id, method, path, key, request_hash)
    except Exception as exc:
        raise _translate_error(exc) from exc
    if replay:
        return JSONResponse(status_code=replay.status_code, content=replay.body)
    return None


@router.get("/profiles")
def profiles() -> dict[str, Any]:
    return {"items": [profile.to_dict() for profile in list_profiles()]}


@router.get("/profiles/{profile_key}/{profile_version}")
def profile(profile_key: str, profile_version: str) -> dict[str, Any]:
    try:
        return get_profile(profile_key, profile_version).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/datasets", status_code=201)
def datasets_create(
    payload: DatasetCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    client_id: Annotated[str, Depends(authenticated_client)],
) -> JSONResponse:
    request_data = payload.model_dump()
    request_hash = body_hash(request_data)
    replay = _replay_or_none(client_id, "POST", request.url.path, idempotency_key, request_hash)
    if replay:
        return replay
    result = create_dataset(get_engine(), client_id=client_id, **request_data)
    store_idempotency(
        get_engine(),
        client_id,
        "POST",
        request.url.path,
        idempotency_key,
        request_hash,
        201,
        result,
    )
    return JSONResponse(status_code=201, content=result)


@router.post("/datasets/{dataset_id}/record-batches", status_code=201)
def record_batches_create(
    dataset_id: str,
    payload: RecordBatchCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    client_id: Annotated[str, Depends(authenticated_client)],
) -> JSONResponse:
    request_data = payload.model_dump()
    request_hash = body_hash(request_data)
    replay = _replay_or_none(client_id, "POST", request.url.path, idempotency_key, request_hash)
    if replay:
        return replay
    try:
        result = append_record_batch(
            get_engine(),
            client_id,
            dataset_id,
            payload.batch_id,
            [record.model_dump() for record in payload.records],
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    store_idempotency(
        get_engine(),
        client_id,
        "POST",
        request.url.path,
        idempotency_key,
        request_hash,
        201,
        result,
    )
    return JSONResponse(status_code=201, content=result)


@router.put("/datasets/{dataset_id}/source-file")
def source_file_upload(
    dataset_id: str,
    request: Request,
    source_file: Annotated[UploadFile, File(alias="file")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    client_id: Annotated[str, Depends(authenticated_client)],
) -> JSONResponse:
    if not source_file.filename or not source_file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Data Referee accepts CSV files only.")
    source_file.file.seek(0, io.SEEK_END)
    size = source_file.file.tell()
    source_file.file.seek(0)
    if size > get_settings().max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV exceeds the configured upload limit.")
    digest = hashlib.sha256()
    while chunk := source_file.file.read(1024 * 1024):
        digest.update(chunk)
    source_file.file.seek(0)
    request_hash = digest.hexdigest()
    replay = _replay_or_none(client_id, "PUT", request.url.path, idempotency_key, request_hash)
    if replay:
        return replay

    total = 0
    try:
        for index, frame in enumerate(
            pd.read_csv(source_file.file, chunksize=1000, dtype=object), start=1
        ):
            if total + len(frame) > get_settings().max_upload_rows:
                raise HTTPException(status_code=413, detail="CSV exceeds the row limit.")
            clean = frame.astype(object).where(pd.notna(frame), None)
            records = [
                {
                    "external_record_id": str(total + offset + 1),
                    "payload": row,
                }
                for offset, row in enumerate(clean.to_dict(orient="records"))
            ]
            append_record_batch(get_engine(), client_id, dataset_id, f"csv-{index:06d}", records)
            total += len(records)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_error(exc) from exc
    result = {
        "dataset_id": dataset_id,
        "filename": source_file.filename,
        "records_appended": total,
        "status": "receiving_records",
    }
    store_idempotency(
        get_engine(), client_id, "PUT", request.url.path, idempotency_key, request_hash, 200, result
    )
    return JSONResponse(status_code=200, content=result)


@router.get("/datasets/{dataset_id}/profile")
def dataset_profile(
    dataset_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
) -> dict[str, Any]:
    with get_engine().connect() as connection:
        owner = connection.execute(
            text(
                "SELECT 1 FROM referee_datasets WHERE id = :dataset_id AND client_id = :client_id"
            ),
            {"dataset_id": dataset_id, "client_id": client_id},
        ).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Dataset not found.")
        records = [
            dict(row["raw_payload"])
            for row in connection.execute(
                text(
                    """
                    SELECT raw_payload FROM referee_raw_records
                    WHERE dataset_id = :dataset_id ORDER BY ordinal
                    """
                ),
                {"dataset_id": dataset_id},
            ).mappings()
        ]
    return profile_records(records)


@router.post("/datasets/{dataset_id}/quality-runs", status_code=202)
def quality_runs_create(
    dataset_id: str,
    payload: QualityRunCreate,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    client_id: Annotated[str, Depends(authenticated_client)],
) -> JSONResponse:
    request_data = {"dataset_id": dataset_id, **payload.model_dump()}
    request_hash = body_hash(request_data)
    replay = _replay_or_none(client_id, "POST", request.url.path, idempotency_key, request_hash)
    if replay:
        return replay
    try:
        result = create_quality_run(
            get_engine(), client_id, dataset_id, payload.profile_key, payload.profile_version
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    store_idempotency(
        get_engine(),
        client_id,
        "POST",
        request.url.path,
        idempotency_key,
        request_hash,
        202,
        result,
    )
    return JSONResponse(status_code=202, content=result)


@router.get("/quality-runs/{run_id}")
def quality_run_status(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
) -> dict[str, Any]:
    try:
        return get_run(get_engine(), client_id, run_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/quality-runs/{run_id}/summary")
def quality_run_summary(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
) -> dict[str, Any]:
    try:
        return get_summary(get_engine(), client_id, run_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/quality-runs/{run_id}/dimensions")
def quality_run_dimensions(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
) -> dict[str, Any]:
    summary = quality_run_summary(run_id, client_id)
    return {"quality_run_id": run_id, "items": summary["dimension_scores"]}


@router.get("/quality-runs/{run_id}/record-results")
def quality_run_record_results(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=250),
) -> dict[str, Any]:
    try:
        return list_record_results(get_engine(), client_id, run_id, cursor, limit)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get("/quality-runs/{run_id}/issues")
def quality_run_issues(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=250),
) -> dict[str, Any]:
    try:
        return list_issues(get_engine(), client_id, run_id, cursor, limit)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.post("/quality-runs/{run_id}/retry", status_code=202)
def quality_run_retry(
    run_id: str,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    client_id: Annotated[str, Depends(authenticated_client)],
) -> JSONResponse:
    request_hash = body_hash({"run_id": run_id})
    replay = _replay_or_none(client_id, "POST", request.url.path, idempotency_key, request_hash)
    if replay:
        return replay
    try:
        result = retry_run(get_engine(), client_id, run_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    store_idempotency(
        get_engine(),
        client_id,
        "POST",
        request.url.path,
        idempotency_key,
        request_hash,
        202,
        result,
    )
    return JSONResponse(status_code=202, content=result)


def _export_generator(run_id: str, client_id: str, classification: str) -> Generator[str]:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["external_record_id", "score", "classification", "payload"])
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)
    with get_engine().connect() as connection:
        rows = connection.execution_options(stream_results=True).execute(
            text(
                """
                SELECT rr.external_record_id, rr.score, rr.classification, raw.raw_payload
                FROM referee_record_results rr
                JOIN referee_quality_runs run ON run.id = rr.run_id
                JOIN referee_datasets dataset ON dataset.id = run.dataset_id
                JOIN referee_raw_records raw ON raw.id = rr.raw_record_id
                WHERE rr.run_id = :run_id AND run.client_id = :client_id
                  AND dataset.status <> 'expired'
                  AND rr.classification = :classification
                ORDER BY rr.id
                """
            ),
            {"run_id": run_id, "client_id": client_id, "classification": classification},
        )
        for row in rows:
            writer.writerow([row[0], row[1], row[2], json.dumps(row[3], default=str)])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)


@router.get("/quality-runs/{run_id}/exports/{classification}.csv")
def quality_run_csv_export(
    run_id: str,
    classification: Literal["accepted", "quarantined", "rejected"],
    client_id: Annotated[str, Depends(authenticated_client)],
) -> StreamingResponse:
    try:
        list_record_results(get_engine(), client_id, run_id, None, 1)
    except Exception as exc:
        raise _translate_error(exc) from exc
    headers = {"Content-Disposition": f'attachment; filename="{classification}-{run_id}.csv"'}
    return StreamingResponse(
        _export_generator(run_id, client_id, classification),
        media_type="text/csv",
        headers=headers,
    )


@router.get("/quality-runs/{run_id}/exports/report.json")
def quality_run_json_report(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
) -> dict[str, Any]:
    return quality_run_summary(run_id, client_id)


@router.get("/quality-runs/{run_id}/exports/report.html", response_class=HTMLResponse)
def quality_run_html_report(
    run_id: str,
    client_id: Annotated[str, Depends(authenticated_client)],
) -> HTMLResponse:
    summary = quality_run_summary(run_id, client_id)
    escaped = json.dumps(summary, indent=2, default=str).replace("&", "&amp;").replace("<", "&lt;")
    return HTMLResponse(
        f"<html><head><title>Data Referee report</title></head>"
        f"<body><h1>{summary.get('verdict', 'Pending')}</h1><pre>{escaped}</pre></body></html>"
    )
