from app.core.engine import evaluate_records
from app.core.models import Classification
from app.core.profiles import GENERIC_PROFILE, LIVE_EVENTS_PROFILE


def valid_event(**overrides):
    event = {
        "event_id": "tm-1",
        "event_name": "Ava Stone Live",
        "event_date": "2026-08-01",
        "artist_name": "Ava Stone",
        "venue_name": "Mission Ballroom",
        "venue_capacity": 3900,
        "latitude": 39.7392,
        "longitude": -104.9903,
        "market": "Denver, CO",
    }
    event.update(overrides)
    return event


def test_allow_warning_does_not_quarantine_record() -> None:
    result = evaluate_records(
        [valid_event(venue_capacity=None)],
        LIVE_EVENTS_PROFILE,
        ["tm-1"],
    )

    record = result.records[0]
    assert record.classification == Classification.ACCEPTED
    assert record.score == 90
    assert result.use_case_eligibility["event_discovery"] == "trusted"
    assert result.use_case_eligibility["venue_capacity_analysis"] == "blocked"


def test_error_quarantines_and_blocker_rejects() -> None:
    result = evaluate_records(
        [
            valid_event(event_id="tm-1", artist_name=None),
            valid_event(event_id=None),
        ],
        LIVE_EVENTS_PROFILE,
        ["row-1", "row-2"],
    )

    assert result.records[0].classification == Classification.QUARANTINED
    assert result.records[1].classification == Classification.REJECTED


def test_generic_exact_duplicates_are_quarantined() -> None:
    result = evaluate_records(
        [{"name": "same"}, {"name": "same"}],
        GENERIC_PROFILE,
        ["1", "2"],
    )

    assert {record.classification for record in result.records} == {
        Classification.QUARANTINED
    }
