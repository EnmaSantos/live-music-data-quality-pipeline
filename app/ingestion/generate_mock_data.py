from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

ARTISTS = [
    ("ART-001", "The Midnight Echo", "Alternative"),
    ("ART-002", "Sofia Reyes", "Pop"),
    ("ART-003", "Northbound Hearts", "Country"),
    ("ART-004", "DJ Meridian", "EDM"),
    ("ART-005", "The Brass Line", "Jazz"),
    ("ART-006", "Ava Stone", "R&B"),
    ("ART-007", "Blue Canyon", "Rock"),
    ("ART-008", "Luna Park", "Indie"),
    ("ART-009", "Orion West", "Hip-Hop"),
    ("ART-010", "Maya Vale", "Singer Songwriter"),
]

DUPLICATE_ARTIST_IDS = {
    "The Midnight Echo": ["ART-001", "ART-001-DUP", "MB-8891"],
    "DJ Meridian": ["ART-004", "SP-7781", "ART-004-ALT"],
    "Ava Stone": ["ART-006", "MB-1006"],
}

VENUES = [
    ("VEN-001", "Summit Hall", "Denver", "CO", 5200, 39.7392, -104.9903),
    ("VEN-002", "Riverside Amphitheatre", "Austin", "TX", 14000, 30.2672, -97.7431),
    ("VEN-003", "Harbor Stage", "Seattle", "WA", 8500, 47.6062, -122.3321),
    ("VEN-004", "Union Theater", "Chicago", "IL", 3200, 41.8781, -87.6298),
    ("VEN-005", "Desert Star Arena", "Phoenix", "AZ", 18000, 33.4484, -112.0740),
    ("VEN-006", "Liberty Pavilion", "Philadelphia", "PA", 9500, 39.9526, -75.1652),
    ("VEN-007", "Crescent Club", "New Orleans", "LA", 1250, 29.9511, -90.0715),
    ("VEN-008", "Wasatch Field", "Salt Lake City", "UT", 22000, 40.7608, -111.8910),
    ("VEN-009", "Mission Ballroom", "San Francisco", "CA", 3900, 37.7749, -122.4194),
    ("VEN-010", "Brooklyn Yard", "New York", "NY", 6700, 40.7128, -74.0060),
]

STATE_VARIANTS = {
    "CA": ["CA", "California", "calif."],
    "CO": ["CO", "Colorado", "colo"],
    "IL": ["IL", "Illinois"],
    "LA": ["LA", "Louisiana"],
    "NY": ["NY", "New York", "new york"],
    "PA": ["PA", "Pennsylvania"],
    "TX": ["TX", "Texas", "tx"],
    "UT": ["UT", "Utah", "utah"],
    "WA": ["WA", "Washington"],
    "AZ": ["AZ", "Arizona"],
}

SOURCES = ["ticketmaster_csv", "musicbrainz_api", "venue_partner_feed", "airplay_mock"]


def _messy_text(value: str) -> str:
    mode = random.random()
    if mode < 0.2:
        return f"  {value.lower()}  "
    if mode < 0.4:
        return value.upper()
    if mode < 0.55:
        return value.replace(" ", "   ")
    return value


def _event_date(base: date) -> str:
    if random.random() < 0.035:
        return random.choice(["2026-99-41", "not a date", "", "13/40/2026"])
    event_day = base + timedelta(days=random.randint(-180, 365))
    return random.choice(
        [
            event_day.isoformat(),
            event_day.strftime("%m/%d/%Y"),
            event_day.strftime("%b %d, %Y"),
        ]
    )


def _maybe_duplicate_artist_id(artist_name: str, artist_id: str) -> str:
    choices = DUPLICATE_ARTIST_IDS.get(artist_name)
    if choices and random.random() < 0.35:
        return random.choice(choices)
    return artist_id


def build_rows(row_count: int, seed: int) -> list[dict[str, object]]:
    random.seed(seed)
    rows: list[dict[str, object]] = []
    base = date(2026, 1, 1)

    for index in range(row_count):
        artist_id, artist_name, genre = random.choice(ARTISTS)
        venue_id, venue_name, city, state, capacity, latitude, longitude = random.choice(VENUES)
        source = random.choice(SOURCES)
        event_id = f"EVT-{index:08d}"

        if random.random() < 0.015 and rows:
            event_id = random.choice(rows)["event_id"]

        row_capacity: Optional[int] = capacity
        if random.random() < 0.08:
            row_capacity = None
        elif random.random() < 0.02:
            row_capacity = -1

        row_latitude = latitude
        row_longitude = longitude
        if random.random() < 0.03:
            row_latitude = random.choice([None, 999, -999])
        if random.random() < 0.03:
            row_longitude = random.choice([None, 999, -999])

        rows.append(
            {
                "source": source,
                "event_id": event_id,
                "event_name": _messy_text(f"{artist_name} Live at {venue_name}"),
                "event_date": _event_date(base),
                "artist_id": _maybe_duplicate_artist_id(artist_name, artist_id),
                "artist_name": _messy_text(artist_name),
                "genre": random.choice([genre, genre.lower(), genre.replace("-", " "), ""]),
                "venue_id": venue_id if random.random() > 0.04 else f"{venue_id}-ALT",
                "venue_name": _messy_text(venue_name),
                "venue_capacity": row_capacity,
                "address": f"{random.randint(10, 9999)} Main St",
                "city": _messy_text(city),
                "state": random.choice(STATE_VARIANTS[state] + ["bad-state"] * 1),
                "country": random.choice(["US", "USA", "United States", ""]),
                "latitude": row_latitude,
                "longitude": row_longitude,
                "market": random.choice([f"{city}, {state}", city, "", _messy_text(city)]),
                "dma_code": str(random.randint(500, 899)),
                "ticket_demand_score": round(random.uniform(10, 100), 2),
                "airplay_spins": random.randint(0, 5000),
            }
        )

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate messy live-music mock event data.")
    parser.add_argument("--rows", type=int, default=100000, help="Number of rows to generate.")
    parser.add_argument("--output", type=Path, default=Path("data/raw/mock_events.csv"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_rows(args.rows, args.seed))
    frame.to_csv(args.output, index=False)
    print(f"Wrote {len(frame):,} rows to {args.output}")


if __name__ == "__main__":
    main()
