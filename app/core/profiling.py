from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from typing import Any

import pandas as pd


def _inferred_type(values: list[Any]) -> str:
    present = [value for value in values if value not in (None, "")]
    if not present:
        return "empty"
    series = pd.Series(present)
    numeric = pd.to_numeric(series, errors="coerce").notna().mean()
    dates = pd.to_datetime(series, errors="coerce", format="mixed").notna().mean()
    if numeric >= 0.95:
        return "number"
    if dates >= 0.95:
        return "date"
    if all(isinstance(value, bool) for value in present):
        return "boolean"
    return "text"


def profile_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    columns = sorted({column for record in records for column in record})
    row_hashes = [json.dumps(record, sort_keys=True, default=str) for record in records]
    duplicate_rows = sum(count - 1 for count in Counter(row_hashes).values() if count > 1)
    column_profiles: list[dict[str, Any]] = []

    for column in columns:
        values = [record.get(column) for record in records]
        present = [value for value in values if value not in (None, "")]
        serializable = [
            value.isoformat() if isinstance(value, (date, datetime)) else value for value in present
        ]
        distinct = {json.dumps(value, sort_keys=True, default=str) for value in serializable}
        column_profiles.append(
            {
                "column_name": column,
                "inferred_type": _inferred_type(values),
                "null_percentage": round(
                    100 * (len(values) - len(present)) / max(len(values), 1), 2
                ),
                "distinct_count": len(distinct),
                "sample_values": serializable[:5],
                "candidate_identifier": bool(present) and len(distinct) == len(present),
            }
        )

    return {
        "rows": len(records),
        "columns": len(columns),
        "duplicate_rows": duplicate_rows,
        "duplicate_percentage": round(100 * duplicate_rows / max(len(records), 1), 2),
        "column_profiles": column_profiles,
    }
