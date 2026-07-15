from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Action(str, Enum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    REJECT = "reject"


class Classification(str, Enum):
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    name: str
    dimension: str
    severity: Severity
    action: Action
    penalty: int
    field_name: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileDefinition:
    profile_key: str
    profile_version: str
    name: str
    description: str
    status: str
    acceptance_threshold: int
    dimension_weights: dict[str, int]
    rules: tuple[RuleDefinition, ...]
    use_case_thresholds: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuleIssue:
    rule_id: str
    dimension: str
    severity: Severity
    action: Action
    field_name: str | None
    message: str
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecordEvaluation:
    external_record_id: str
    score: int
    classification: Classification
    issues: tuple[RuleIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        issues = [issue.to_dict() for issue in self.issues]
        return {
            "external_record_id": self.external_record_id,
            "score": self.score,
            "classification": self.classification.value,
            "warning_count": sum(issue.severity == Severity.WARNING for issue in self.issues),
            "error_count": sum(
                issue.severity in {Severity.ERROR, Severity.CRITICAL} for issue in self.issues
            ),
            "issues": issues,
        }


@dataclass(frozen=True)
class EvaluationResult:
    profile_key: str
    profile_version: str
    overall_score: float
    verdict: str
    dimension_scores: dict[str, float]
    classification_counts: dict[str, int]
    use_case_eligibility: dict[str, str]
    records: tuple[RecordEvaluation, ...]

    def summary_dict(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "profile_version": self.profile_version,
            "overall_score": self.overall_score,
            "verdict": self.verdict,
            "dimension_scores": self.dimension_scores,
            "classification_counts": self.classification_counts,
            "blocked_use_cases": [
                name for name, status in self.use_case_eligibility.items() if status == "blocked"
            ],
            "use_case_eligibility": self.use_case_eligibility,
        }
