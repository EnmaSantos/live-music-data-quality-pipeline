from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

import pandas as pd

EXPECTED_COLUMNS = [
    "source",
    "event_id",
    "event_name",
    "event_date",
    "artist_id",
    "artist_name",
    "genre",
    "venue_id",
    "venue_name",
    "venue_capacity",
    "address",
    "city",
    "state",
    "country",
    "latitude",
    "longitude",
    "market",
    "dma_code",
    "ticket_demand_score",
    "airplay_spins",
]

STATE_ALIASES = {
    "ALABAMA": "AL",
    "ARIZONA": "AZ",
    "CALIF": "CA",
    "CALIFORNIA": "CA",
    "COLO": "CO",
    "COLORADO": "CO",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "LOUISIANA": "LA",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "NEVADA": "NV",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "OHIO": "OH",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "WASHINGTON": "WA",
}

VALID_STATE_CODES = set(STATE_ALIASES.values())

GENRE_ALIASES = {
    "alt rock": "Alternative",
    "alternative rock": "Alternative",
    "country music": "Country",
    "edm": "Electronic",
    "electronic dance": "Electronic",
    "hip hop": "Hip-Hop",
    "hip-hop": "Hip-Hop",
    "indie-rock": "Indie",
    "r&b": "R&B",
    "rhythm and blues": "R&B",
    "rock n roll": "Rock",
    "singer songwriter": "Singer-Songwriter",
}


def clean_text(value: Any) -> Optional[str]:
    if pd.isna(value):
        return None
    text = str(value).replace("\u00a0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def normalize_display_name(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    text = text.strip(" -_")
    return text.title()


def normalize_state(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    compact = re.sub(r"[^A-Za-z]", "", text).upper()
    if len(compact) == 2:
        return compact
    return STATE_ALIASES.get(compact) or STATE_ALIASES.get(text.upper())


def normalize_country(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return "US"
    compact = text.upper()
    if compact in {"USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "US"
    return compact


def normalize_genre(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    key = text.lower().replace("/", " ").replace("_", " ")
    key = re.sub(r"\s+", " ", key).strip()
    return GENRE_ALIASES.get(key, text.title())


def normalize_market(market: Any, city: Any, state: Any) -> Optional[str]:
    state_text = normalize_state(state)
    raw_market = clean_text(market)
    if raw_market and "," in raw_market:
        market_city, market_state = raw_market.rsplit(",", 1)
        city_text = normalize_display_name(market_city)
        state_text = normalize_state(market_state) or state_text
        if city_text and state_text:
            return f"{city_text}, {state_text}"
    market_text = normalize_display_name(raw_market)
    if market_text and state_text:
        return f"{market_text}, {state_text}"
    if market_text:
        return market_text
    city_text = normalize_display_name(city)
    if city_text and state_text:
        return f"{city_text}, {state_text}"
    return city_text


def fingerprint(*parts: Any) -> Optional[str]:
    tokens: list[str] = []
    for part in parts:
        text = clean_text(part)
        if text:
            tokens.append(re.sub(r"[^a-z0-9]+", "", text.lower()))
    joined = "|".join(token for token in tokens if token)
    if not joined:
        return None
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _series_or_none(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([None] * len(frame), index=frame.index)


def normalize_frame(raw_frame: pd.DataFrame, source_name: Optional[str] = None) -> pd.DataFrame:
    frame = raw_frame.copy()
    for column in EXPECTED_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    normalized = pd.DataFrame(index=frame.index)
    normalized["source"] = _series_or_none(frame, "source").map(clean_text)
    normalized["source"] = normalized["source"].fillna(source_name or "csv")
    normalized["source_event_id"] = frame["event_id"].map(clean_text)
    normalized["source_artist_id"] = frame["artist_id"].map(clean_text)
    normalized["source_venue_id"] = frame["venue_id"].map(clean_text)

    normalized["event_name_raw"] = frame["event_name"].map(clean_text)
    normalized["event_name_clean"] = frame["event_name"].map(normalize_display_name)
    normalized["event_date_raw"] = frame["event_date"].map(clean_text)
    normalized["event_date"] = pd.to_datetime(
        frame["event_date"],
        errors="coerce",
        format="mixed",
        utc=False,
    ).dt.date

    normalized["artist_name_raw"] = frame["artist_name"].map(clean_text)
    normalized["artist_name_clean"] = frame["artist_name"].map(normalize_display_name)
    normalized["genre_clean"] = frame["genre"].map(normalize_genre)

    normalized["venue_name_raw"] = frame["venue_name"].map(clean_text)
    normalized["venue_name_clean"] = frame["venue_name"].map(normalize_display_name)
    normalized["venue_capacity"] = (
        pd.to_numeric(frame["venue_capacity"], errors="coerce").round().astype("Int64")
    )
    normalized["address"] = frame["address"].map(clean_text)
    normalized["city_clean"] = frame["city"].map(normalize_display_name)
    normalized["state_clean"] = frame["state"].map(normalize_state)
    normalized["country_clean"] = frame["country"].map(normalize_country)
    normalized["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    normalized["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    normalized["market_clean"] = [
        normalize_market(market, city, state)
        for market, city, state in zip(frame["market"], frame["city"], frame["state"])
    ]
    normalized["dma_code"] = frame["dma_code"].map(clean_text)
    normalized["ticket_demand_score"] = pd.to_numeric(
        frame["ticket_demand_score"],
        errors="coerce",
    )
    normalized["airplay_spins"] = (
        pd.to_numeric(frame["airplay_spins"], errors="coerce").round().astype("Int64")
    )

    normalized["artist_fingerprint"] = [
        fingerprint(name) for name in normalized["artist_name_clean"]
    ]
    normalized["venue_fingerprint"] = [
        fingerprint(name, city, state)
        for name, city, state in zip(
            normalized["venue_name_clean"],
            normalized["city_clean"],
            normalized["state_clean"],
        )
    ]
    normalized["event_fingerprint"] = [
        fingerprint(event, artist, venue, date)
        for event, artist, venue, date in zip(
            normalized["event_name_clean"],
            normalized["artist_fingerprint"],
            normalized["venue_fingerprint"],
            normalized["event_date"],
        )
    ]

    return normalized


def dataframe_for_sql(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.astype(object).where(pd.notna(frame), None)
