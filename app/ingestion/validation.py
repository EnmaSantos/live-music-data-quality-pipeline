from __future__ import annotations

from typing import Any

import pandas as pd

from app.ingestion.normalize import VALID_STATE_CODES, clean_text

ISSUE_WEIGHTS = {
    "critical": 40,
    "error": 25,
    "warning": 10,
    "info": 5,
}


def _missing(value: Any) -> bool:
    return pd.isna(value) or clean_text(value) is None


def _invalid_latitude(value: Any) -> bool:
    return pd.isna(value) or float(value) < -90 or float(value) > 90


def _invalid_longitude(value: Any) -> bool:
    return pd.isna(value) or float(value) < -180 or float(value) > 180


def validate_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    issues: list[dict[str, Any]] = []
    scores = pd.Series([100] * len(frame), index=frame.index, dtype="int64")

    def add_issue(
        row_index: Any,
        entity_type: str,
        entity_key: Any,
        issue_type: str,
        severity: str,
        field_name: str,
        raw_value: Any,
        message: str,
    ) -> None:
        row = frame.loc[row_index]
        issues.append(
            {
                "source": row["source"],
                "event_fingerprint": row["event_fingerprint"],
                "entity_type": entity_type,
                "entity_key": clean_text(entity_key) or clean_text(row["event_fingerprint"]),
                "issue_type": issue_type,
                "severity": severity,
                "field_name": field_name,
                "raw_value": clean_text(raw_value),
                "message": message,
            }
        )
        scores.loc[row_index] = max(0, scores.loc[row_index] - ISSUE_WEIGHTS[severity])

    for row_index, row in frame.iterrows():
        event_key = row["event_fingerprint"] or row["source_event_id"] or f"row-{row_index}"

        if _missing(row["artist_name_clean"]):
            add_issue(
                row_index,
                "artist",
                event_key,
                "missing_artist_name",
                "error",
                "artist_name",
                row["artist_name_raw"],
                "Artist name is missing after normalization.",
            )

        if _missing(row["venue_name_clean"]):
            add_issue(
                row_index,
                "venue",
                event_key,
                "missing_venue_name",
                "error",
                "venue_name",
                row["venue_name_raw"],
                "Venue name is missing after normalization.",
            )

        if pd.isna(row["event_date"]):
            add_issue(
                row_index,
                "event",
                event_key,
                "malformed_event_date",
                "critical",
                "event_date",
                row["event_date_raw"],
                "Event date could not be parsed into a valid date.",
            )

        if pd.isna(row["venue_capacity"]) or row["venue_capacity"] <= 0:
            add_issue(
                row_index,
                "venue",
                row["venue_fingerprint"] or event_key,
                "missing_venue_capacity",
                "warning",
                "venue_capacity",
                row["venue_capacity"],
                "Venue capacity is missing or not positive.",
            )

        if _invalid_latitude(row["latitude"]) or _invalid_longitude(row["longitude"]):
            add_issue(
                row_index,
                "venue",
                row["venue_fingerprint"] or event_key,
                "invalid_coordinates",
                "warning",
                "latitude/longitude",
                f"{row['latitude']},{row['longitude']}",
                "Venue coordinates are missing or outside valid latitude/longitude ranges.",
            )

        if row["state_clean"] not in VALID_STATE_CODES:
            add_issue(
                row_index,
                "market",
                row["market_clean"] or event_key,
                "invalid_state",
                "warning",
                "state",
                row["state_clean"],
                "State is missing or not a recognized US state code.",
            )

    if "source_event_id" in frame.columns:
        duplicate_ids = frame["source_event_id"].dropna()
        duplicate_ids = duplicate_ids[duplicate_ids.duplicated(keep=False)].unique()
        duplicate_mask = frame["source_event_id"].isin(duplicate_ids)
        for row_index, row in frame[duplicate_mask].iterrows():
            add_issue(
                row_index,
                "event",
                row["source_event_id"],
                "duplicate_source_event_id",
                "warning",
                "event_id",
                row["source_event_id"],
                "The same source event id appears more than once in this ingestion chunk.",
            )

    return pd.DataFrame(issues), scores
