import pandas as pd

from app.ingestion.normalize import normalize_frame
from app.ingestion.validation import validate_frame


def test_validate_frame_flags_expected_quality_issues() -> None:
    raw = pd.DataFrame(
        [
            {
                "source": "ticketmaster_csv",
                "event_id": "EVT-1",
                "event_name": "Bad Coordinates Show",
                "event_date": "not a date",
                "artist_id": "ART-1",
                "artist_name": "Ava Stone",
                "genre": "R&B",
                "venue_id": "VEN-1",
                "venue_name": "Mission Ballroom",
                "venue_capacity": "",
                "address": "900 Valencia St",
                "city": "San Francisco",
                "state": "bad-state",
                "country": "US",
                "latitude": "999",
                "longitude": "-122.4194",
                "market": "San Francisco",
                "dma_code": "807",
                "ticket_demand_score": "88.4",
                "airplay_spins": "300",
            }
        ]
    )
    clean = normalize_frame(raw)
    issues, scores = validate_frame(clean)

    issue_types = set(issues["issue_type"])

    assert "malformed_event_date" in issue_types
    assert "missing_venue_capacity" in issue_types
    assert "invalid_coordinates" in issue_types
    assert "invalid_state" in issue_types
    assert scores.iloc[0] < 100


def test_validate_frame_flags_duplicate_source_event_ids() -> None:
    raw = pd.DataFrame(
        [
            {
                "source": "ticketmaster_csv",
                "event_id": "EVT-1",
                "event_name": "Show One",
                "event_date": "2026-01-01",
                "artist_id": "ART-1",
                "artist_name": "Ava Stone",
                "genre": "R&B",
                "venue_id": "VEN-1",
                "venue_name": "Mission Ballroom",
                "venue_capacity": "3900",
                "address": "900 Valencia St",
                "city": "San Francisco",
                "state": "CA",
                "country": "US",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "market": "San Francisco",
                "dma_code": "807",
                "ticket_demand_score": "88.4",
                "airplay_spins": "300",
            },
            {
                "source": "ticketmaster_csv",
                "event_id": "EVT-1",
                "event_name": "Show One",
                "event_date": "2026-01-01",
                "artist_id": "ART-1",
                "artist_name": "Ava Stone",
                "genre": "R&B",
                "venue_id": "VEN-1",
                "venue_name": "Mission Ballroom",
                "venue_capacity": "3900",
                "address": "900 Valencia St",
                "city": "San Francisco",
                "state": "CA",
                "country": "US",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "market": "San Francisco",
                "dma_code": "807",
                "ticket_demand_score": "88.4",
                "airplay_spins": "300",
            },
        ]
    )
    clean = normalize_frame(raw)
    issues, _ = validate_frame(clean)

    assert (issues["issue_type"] == "duplicate_source_event_id").sum() == 2
