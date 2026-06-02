import pandas as pd

from app.ingestion.ticketmaster import event_to_row, write_events_csv


def test_event_to_row_maps_ticketmaster_payload() -> None:
    event = {
        "id": "evt-1",
        "name": "Ava Stone Live",
        "dates": {"start": {"localDate": "2026-07-12"}},
        "classifications": [
            {
                "segment": {"name": "Music"},
                "genre": {"name": "R&B"},
                "subGenre": {"name": "Soul"},
            }
        ],
        "_embedded": {
            "attractions": [
                {
                    "id": "artist-1",
                    "name": "Ava Stone",
                    "classifications": [{"segment": {"name": "Music"}}],
                }
            ],
            "venues": [
                {
                    "id": "venue-1",
                    "name": "Mission Ballroom",
                    "address": {"line1": "900 Valencia St"},
                    "city": {"name": "San Francisco"},
                    "state": {"stateCode": "CA"},
                    "country": {"countryCode": "US"},
                    "location": {"latitude": "37.7749", "longitude": "-122.4194"},
                    "markets": [{"name": "San Francisco, CA"}],
                    "dmas": [{"id": 807}],
                }
            ],
        },
    }

    row = event_to_row(event)

    assert row["source"] == "ticketmaster_api"
    assert row["event_id"] == "evt-1"
    assert row["event_date"] == "2026-07-12"
    assert row["artist_name"] == "Ava Stone"
    assert row["venue_name"] == "Mission Ballroom"
    assert row["genre"] == "R&B"
    assert row["market"] == "San Francisco, CA"


def test_event_to_row_uses_custom_source_name() -> None:
    row = event_to_row({"id": "evt-1", "name": "Ava Stone Live"}, source_name="artist_pull")

    assert row["source"] == "artist_pull"


def test_write_events_csv_keeps_headers_for_empty_results(tmp_path) -> None:
    output_path = tmp_path / "empty_ticketmaster.csv"

    write_events_csv([], output_path)

    frame = pd.read_csv(output_path)
    assert list(frame.columns)[:3] == ["source", "event_id", "event_name"]
    assert frame.empty
