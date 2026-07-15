from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime
from typing import Any

import pandas as pd

from app.core.models import (
    Action,
    Classification,
    EvaluationResult,
    ProfileDefinition,
    RecordEvaluation,
    RuleDefinition,
    RuleIssue,
    Severity,
)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _valid_date(value: Any) -> bool:
    if _missing(value):
        return False
    if isinstance(value, (date, datetime)):
        return True
    return not pd.isna(pd.to_datetime(value, errors="coerce"))


def _valid_coordinates(record: dict[str, Any]) -> bool:
    try:
        latitude = float(record.get("latitude"))
        longitude = float(record.get("longitude"))
    except (TypeError, ValueError):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _payload_hash(record: dict[str, Any]) -> str:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _failed(
    rule: RuleDefinition,
    record: dict[str, Any],
    duplicate_event_ids: set[str],
    duplicate_payloads: set[str],
) -> bool:
    rule_id = rule.rule_id
    if rule_id == "generic.row.not_empty":
        return all(_missing(value) for value in record.values())
    if rule_id == "generic.row.unique":
        return _payload_hash(record) in duplicate_payloads
    if rule_id.endswith("event_id.required"):
        return _missing(record.get("event_id"))
    if rule_id.endswith("event_name.required"):
        return _missing(record.get("event_name"))
    if rule_id.endswith("event_date.valid"):
        return not _valid_date(record.get("event_date"))
    if rule_id.endswith("artist_name.required"):
        return _missing(record.get("artist_name"))
    if rule_id.endswith("venue_name.required"):
        return _missing(record.get("venue_name"))
    if rule_id.endswith("venue_capacity.positive"):
        return not _positive(record.get("venue_capacity"))
    if rule_id.endswith("coordinates.valid"):
        return not _valid_coordinates(record)
    if rule_id.endswith("market.present"):
        return _missing(record.get("market"))
    if rule_id.endswith("event_id.unique"):
        value = record.get("event_id")
        return not _missing(value) and str(value) in duplicate_event_ids
    raise ValueError(f"No evaluator registered for rule {rule.rule_id}")


def _classification(issues: list[RuleIssue], score: int, threshold: int) -> Classification:
    if any(issue.action == Action.REJECT for issue in issues):
        return Classification.REJECTED
    if (
        any(issue.action == Action.QUARANTINE for issue in issues)
        or any(issue.severity in {Severity.ERROR, Severity.CRITICAL} for issue in issues)
        or score < threshold
    ):
        return Classification.QUARANTINED
    return Classification.ACCEPTED


def _eligibility(value: float, thresholds: dict[str, float], lower_is_better: bool) -> str:
    if lower_is_better:
        if value <= thresholds["trusted_max"]:
            return "trusted"
        if value > thresholds["blocked_above"]:
            return "blocked"
        return "caution"
    if value >= thresholds["trusted_min"]:
        return "trusted"
    if value < thresholds["blocked_below"]:
        return "blocked"
    return "caution"


def _use_case_eligibility(
    profile: ProfileDefinition,
    records: list[dict[str, Any]],
    classification_counts: Counter[str],
) -> dict[str, str]:
    if profile.profile_key != "live-events":
        return {}
    total = max(len(records), 1)
    rejected_pct = 100 * classification_counts[Classification.REJECTED.value] / total
    valid_market = 100 * sum(not _missing(record.get("market")) for record in records) / total
    valid_coordinates = 100 * sum(_valid_coordinates(record) for record in records) / total
    valid_capacity = (
        100 * sum(_positive(record.get("venue_capacity")) for record in records) / total
    )
    valid_artist = 100 * sum(not _missing(record.get("artist_name")) for record in records) / total
    thresholds = profile.use_case_thresholds
    return {
        "event_discovery": _eligibility(
            rejected_pct, thresholds["event_discovery"], lower_is_better=True
        ),
        "market_analysis": _eligibility(
            valid_market, thresholds["market_analysis"], lower_is_better=False
        ),
        "geographic_analysis": _eligibility(
            valid_coordinates, thresholds["geographic_analysis"], lower_is_better=False
        ),
        "venue_capacity_analysis": _eligibility(
            valid_capacity, thresholds["venue_capacity_analysis"], lower_is_better=False
        ),
        "artist_reporting": _eligibility(
            valid_artist, thresholds["artist_reporting"], lower_is_better=False
        ),
    }


def evaluate_records(
    records: list[dict[str, Any]],
    profile: ProfileDefinition,
    external_record_ids: list[str] | None = None,
) -> EvaluationResult:
    ids = external_record_ids or [str(index + 1) for index in range(len(records))]
    event_ids = [
        str(record["event_id"]) for record in records if not _missing(record.get("event_id"))
    ]
    duplicate_event_ids = {value for value, count in Counter(event_ids).items() if count > 1}
    payload_hashes = [_payload_hash(record) for record in records]
    duplicate_payloads = {value for value, count in Counter(payload_hashes).items() if count > 1}
    evaluations: list[RecordEvaluation] = []
    dimension_penalties: Counter[str] = Counter()

    for external_id, record in zip(ids, records):
        issues: list[RuleIssue] = []
        for rule in profile.rules:
            if _failed(rule, record, duplicate_event_ids, duplicate_payloads):
                issues.append(
                    RuleIssue(
                        rule_id=rule.rule_id,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        action=rule.action,
                        field_name=rule.field_name,
                        message=f"{rule.name} failed.",
                        recommendation=rule.recommendation,
                    )
                )
                dimension_penalties[rule.dimension] += rule.penalty
        score = max(
            0,
            100
            - sum(
                next(rule.penalty for rule in profile.rules if rule.rule_id == issue.rule_id)
                for issue in issues
            ),
        )
        evaluations.append(
            RecordEvaluation(
                external_record_id=str(external_id),
                score=score,
                classification=_classification(issues, score, profile.acceptance_threshold),
                issues=tuple(issues),
            )
        )

    total = max(len(records), 1)
    dimension_scores = {
        dimension: round(max(0.0, 100 - dimension_penalties[dimension] / total), 2)
        for dimension in profile.dimension_weights
    }
    overall_score = round(
        sum(
            dimension_scores[dimension] * weight / 100
            for dimension, weight in profile.dimension_weights.items()
        ),
        2,
    )
    verdict = (
        "trusted"
        if overall_score >= 90
        else "needs_attention"
        if overall_score >= 75
        else "high_risk"
        if overall_score >= 50
        else "unsafe"
    )
    counts: Counter[str] = Counter(evaluation.classification.value for evaluation in evaluations)
    classification_counts = {
        classification.value: counts[classification.value] for classification in Classification
    }
    return EvaluationResult(
        profile_key=profile.profile_key,
        profile_version=profile.profile_version,
        overall_score=overall_score,
        verdict=verdict,
        dimension_scores=dimension_scores,
        classification_counts=classification_counts,
        use_case_eligibility=_use_case_eligibility(profile, records, counts),
        records=tuple(evaluations),
    )
