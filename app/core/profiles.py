from __future__ import annotations

from app.core.models import Action, ProfileDefinition, RuleDefinition, Severity

GENERIC_PROFILE = ProfileDefinition(
    profile_key="generic",
    profile_version="1.0.0",
    name="Generic tabular data",
    description="Safe structural checks that do not assume domain-specific required fields.",
    status="published",
    acceptance_threshold=90,
    dimension_weights={
        "completeness": 25,
        "validity": 25,
        "consistency": 15,
        "uniqueness": 15,
        "integrity": 15,
        "freshness": 5,
    },
    rules=(
        RuleDefinition(
            "generic.row.not_empty",
            "Row contains at least one value",
            "completeness",
            Severity.ERROR,
            Action.QUARANTINE,
            25,
            recommendation="Remove empty rows before analysis.",
        ),
        RuleDefinition(
            "generic.row.unique",
            "Row is not an exact duplicate",
            "uniqueness",
            Severity.WARNING,
            Action.QUARANTINE,
            10,
            recommendation="Confirm whether exact duplicates should be deduplicated.",
        ),
    ),
)


LIVE_EVENTS_PROFILE = ProfileDefinition(
    profile_key="live-events",
    profile_version="1.0.0",
    name="Live-event data",
    description="Trust checks for event discovery, markets, artists, venues, and coordinates.",
    status="published",
    acceptance_threshold=75,
    dimension_weights={
        "completeness": 20,
        "validity": 25,
        "consistency": 10,
        "uniqueness": 15,
        "integrity": 15,
        "freshness": 15,
    },
    rules=(
        RuleDefinition(
            "live_events.event_id.required",
            "Event identifier is present",
            "completeness",
            Severity.CRITICAL,
            Action.REJECT,
            40,
            "event_id",
        ),
        RuleDefinition(
            "live_events.event_name.required",
            "Event name is present",
            "completeness",
            Severity.CRITICAL,
            Action.REJECT,
            40,
            "event_name",
        ),
        RuleDefinition(
            "live_events.event_date.valid",
            "Event date is parseable",
            "validity",
            Severity.CRITICAL,
            Action.REJECT,
            40,
            "event_date",
        ),
        RuleDefinition(
            "live_events.artist_name.required",
            "Artist name is present",
            "completeness",
            Severity.ERROR,
            Action.QUARANTINE,
            25,
            "artist_name",
        ),
        RuleDefinition(
            "live_events.venue_name.required",
            "Venue name is present",
            "completeness",
            Severity.ERROR,
            Action.QUARANTINE,
            25,
            "venue_name",
        ),
        RuleDefinition(
            "live_events.venue_capacity.positive",
            "Venue capacity is positive when available",
            "completeness",
            Severity.WARNING,
            Action.ALLOW,
            10,
            "venue_capacity",
            "Enrich venue capacity before capacity-based analysis.",
        ),
        RuleDefinition(
            "live_events.coordinates.valid",
            "Venue coordinates are valid",
            "validity",
            Severity.WARNING,
            Action.ALLOW,
            10,
            "latitude/longitude",
            "Correct or enrich coordinates before geographic analysis.",
        ),
        RuleDefinition(
            "live_events.market.present",
            "Market is present",
            "completeness",
            Severity.WARNING,
            Action.ALLOW,
            10,
            "market",
        ),
        RuleDefinition(
            "live_events.event_id.unique",
            "Event identifier is unique",
            "uniqueness",
            Severity.WARNING,
            Action.QUARANTINE,
            10,
            "event_id",
        ),
    ),
    use_case_thresholds={
        "event_discovery": {"trusted_max": 1.0, "blocked_above": 5.0},
        "market_analysis": {"trusted_min": 95.0, "blocked_below": 80.0},
        "geographic_analysis": {"trusted_min": 95.0, "blocked_below": 80.0},
        "venue_capacity_analysis": {"trusted_min": 95.0, "blocked_below": 80.0},
        "artist_reporting": {"trusted_min": 95.0, "blocked_below": 80.0},
    },
)


_PROFILES = {
    (GENERIC_PROFILE.profile_key, GENERIC_PROFILE.profile_version): GENERIC_PROFILE,
    (LIVE_EVENTS_PROFILE.profile_key, LIVE_EVENTS_PROFILE.profile_version): LIVE_EVENTS_PROFILE,
}


def get_profile(profile_key: str, profile_version: str | None = None) -> ProfileDefinition:
    candidates = [
        profile
        for (key, _), profile in _PROFILES.items()
        if key == profile_key
        and (profile_version is None or profile.profile_version == profile_version)
    ]
    if not candidates:
        raise KeyError(f"Unknown profile: {profile_key}@{profile_version or 'latest'}")
    return sorted(candidates, key=lambda profile: profile.profile_version)[-1]


def list_profiles() -> list[ProfileDefinition]:
    return sorted(_PROFILES.values(), key=lambda profile: profile.profile_key)
