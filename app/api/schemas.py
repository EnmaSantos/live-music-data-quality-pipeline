from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="csv", max_length=50)
    retention_hours: int = Field(default=24, ge=1, le=24 * 30)
    column_mapping: dict[str, str] = Field(default_factory=dict)


class RecordEnvelope(BaseModel):
    external_record_id: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any]


class RecordBatchCreate(BaseModel):
    batch_id: str = Field(min_length=1, max_length=500)
    records: list[RecordEnvelope] = Field(max_length=1000)


class QualityRunCreate(BaseModel):
    profile_key: str
    profile_version: str | None = None
