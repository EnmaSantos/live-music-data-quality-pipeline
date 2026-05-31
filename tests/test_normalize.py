import pandas as pd

from app.ingestion.normalize import (
    fingerprint,
    normalize_frame,
    normalize_genre,
    normalize_market,
    normalize_state,
)


def test_normalize_state_and_genre_aliases() -> None:
    assert normalize_state("California") == "CA"
    assert normalize_state(" tx ") == "TX"
    assert normalize_state("New York") == "NY"
    assert normalize_genre("alt rock") == "Alternative"
    assert normalize_genre("Rhythm and Blues") == "R&B"
    assert normalize_market("denver, co", "Denver", "Colorado") == "Denver, CO"
    assert normalize_market("Denver", "Denver", "Colorado") == "Denver, CO"


def test_fingerprint_ignores_case_spacing_and_punctuation() -> None:
    first = fingerprint(" The Midnight Echo ")
    second = fingerprint("the   midnight echo!!!")

    assert first == second
    assert first is not None


def test_normalize_frame_builds_clean_fields() -> None:
    raw = pd.DataFrame(
        [
            {
                "source": "ticketmaster_csv",
                "event_id": "EVT-1",
                "event_name": "  ava stone live ",
                "event_date": "2026-04-19",
                "artist_id": "ART-1",
                "artist_name": " ava stone ",
                "genre": "r&b",
                "venue_id": "VEN-1",
                "venue_name": " mission ballroom ",
                "venue_capacity": "3900",
                "address": "900 Valencia St",
                "city": "san francisco",
                "state": "California",
                "country": "USA",
                "latitude": "37.7749",
                "longitude": "-122.4194",
                "market": "",
                "dma_code": "807",
                "ticket_demand_score": "88.4",
                "airplay_spins": "300",
            }
        ]
    )

    clean = normalize_frame(raw)

    assert clean.loc[0, "artist_name_clean"] == "Ava Stone"
    assert clean.loc[0, "state_clean"] == "CA"
    assert clean.loc[0, "market_clean"] == "San Francisco, CA"
    assert clean.loc[0, "artist_fingerprint"] is not None
    assert clean.loc[0, "venue_fingerprint"] is not None
