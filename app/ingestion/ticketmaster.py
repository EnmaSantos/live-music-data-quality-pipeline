from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app.ingestion.pipeline import load_csv

DISCOVERY_EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
SOURCE_NAME = "ticketmaster_api"


def _first(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return items[0] if items else {}


def _nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _classification_name(event: dict[str, Any], key: str) -> str | None:
    classification = _first(event.get("classifications"))
    value = _nested(classification, key, "name")
    if value and value != "Undefined":
        return str(value)
    return None


def _artist_for_event(event: dict[str, Any]) -> dict[str, Any]:
    attractions = _nested(event, "_embedded", "attractions")
    if not attractions:
        return {}

    for attraction in attractions:
        classifications = attraction.get("classifications") or []
        for classification in classifications:
            if _nested(classification, "segment", "name") == "Music":
                return attraction

    return _first(attractions)


def _venue_for_event(event: dict[str, Any]) -> dict[str, Any]:
    return _first(_nested(event, "_embedded", "venues"))


def event_to_row(event: dict[str, Any]) -> dict[str, Any]:
    artist = _artist_for_event(event)
    venue = _venue_for_event(event)
    city = _nested(venue, "city", "name")
    state = _nested(venue, "state", "stateCode") or _nested(venue, "state", "name")
    market = _nested(_first(venue.get("markets")), "name")

    genre = (
        _classification_name(event, "genre")
        or _classification_name(event, "subGenre")
        or _nested(_first(artist.get("classifications")), "genre", "name")
    )

    return {
        "source": SOURCE_NAME,
        "event_id": event.get("id"),
        "event_name": event.get("name"),
        "event_date": _nested(event, "dates", "start", "localDate")
        or _nested(event, "dates", "start", "dateTime"),
        "artist_id": artist.get("id"),
        "artist_name": artist.get("name"),
        "genre": genre,
        "venue_id": venue.get("id"),
        "venue_name": venue.get("name"),
        "venue_capacity": None,
        "address": _nested(venue, "address", "line1"),
        "city": city,
        "state": state,
        "country": _nested(venue, "country", "countryCode"),
        "latitude": _nested(venue, "location", "latitude"),
        "longitude": _nested(venue, "location", "longitude"),
        "market": market or (f"{city}, {state}" if city and state else city),
        "dma_code": _nested(_first(venue.get("dmas")), "id"),
        "ticket_demand_score": None,
        "airplay_spins": None,
    }


def fetch_events(
    api_key: str,
    city: str | None = None,
    state: str | None = None,
    country: str = "US",
    pages: int = 1,
    size: int = 200,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = min(max(size, 1), 200)

    for page in range(max(pages, 1)):
        params = {
            "apikey": api_key,
            "classificationName": "music",
            "countryCode": country,
            "size": page_size,
            "page": page,
            "sort": "date,asc",
        }
        if city:
            params["city"] = city
        if state:
            params["stateCode"] = state

        url = f"{DISCOVERY_EVENTS_URL}?{urlencode(params)}"
        request = Request(url, headers={"Accept": "application/json"})

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ticketmaster API returned HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not reach Ticketmaster API: {exc.reason}") from exc

        events = _nested(payload, "_embedded", "events") or []
        rows.extend(event_to_row(event) for event in events)

        page_info = payload.get("page") or {}
        total_pages = page_info.get("totalPages")
        if total_pages is not None and page + 1 >= int(total_pages):
            break
        if not events:
            break

    return rows


def write_events_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch real music events from Ticketmaster.")
    parser.add_argument("--api-key", default=os.getenv("TICKETMASTER_API_KEY"))
    parser.add_argument("--city", default="Denver")
    parser.add_argument("--state", default="CO")
    parser.add_argument("--country", default="US")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--output", type=Path, default=Path("data/raw/ticketmaster_events.csv"))
    parser.add_argument("--load", action="store_true", help="Load the fetched CSV into PostgreSQL.")
    parser.add_argument("--replace", action="store_true", help="Replace existing loaded data.")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit(
            "Missing Ticketmaster API key. Add TICKETMASTER_API_KEY to .env "
            "or pass --api-key."
        )

    rows = fetch_events(
        api_key=args.api_key,
        city=args.city,
        state=args.state,
        country=args.country,
        pages=args.pages,
        size=args.size,
    )
    write_events_csv(rows, args.output)
    print(f"Wrote {len(rows):,} Ticketmaster events to {args.output}")

    if args.load:
        result = load_csv(args.output, source_name=SOURCE_NAME, replace=args.replace)
        print(result)


if __name__ == "__main__":
    main()
