from app.ingestion.ticketmaster import event_to_row


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
