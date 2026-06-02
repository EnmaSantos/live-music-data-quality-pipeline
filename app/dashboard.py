from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.db import fetch_all, fetch_one, ping_database
from app.ingestion.pipeline import load_csv

SAMPLE_CSV = Path("data/raw/sample_events.csv")

SOURCE_LABELS = {
    "ticketmaster_api": "Ticketmaster Market Pull",
    "sample_events": "Sample Data",
    "ticketmaster_csv": "Ticketmaster CSV",
    "musicbrainz_api": "MusicBrainz",
    "venue_partner_feed": "Venue Partner Feed",
    "airplay_mock": "Airplay Mock",
}

ISSUE_LABELS = {
    "missing_venue_capacity": "Venue capacity missing",
    "missing_artist_name": "Artist name missing",
    "missing_venue_name": "Venue name missing",
    "malformed_event_date": "Event date unreadable",
    "invalid_coordinates": "Coordinates need review",
    "invalid_state": "Market/state needs review",
    "duplicate_artist_candidate": "Possible duplicate artist",
    "duplicate_venue_candidate": "Possible duplicate venue",
    "duplicate_source_event_id": "Duplicate event ID",
}

STATUS_LABELS = {
    "completed": "Completed",
    "failed": "Failed",
    "running": "Running",
}

COLUMN_LABELS = {
    "source": "Data Source",
    "source_name": "Data Source",
    "event_records": "Events",
    "records_seen": "Rows Found",
    "records_loaded": "Rows Loaded",
    "unique_artists": "Artists",
    "unique_artist_count": "Artists",
    "unique_venues": "Venues",
    "unique_venue_count": "Venues",
    "avg_quality_score": "Data Health Score",
    "issue_count": "Open Issues",
    "critical_issues": "Critical Issues",
    "error_issues": "Errors",
    "warning_issues": "Warnings",
    "info_issues": "Notes",
    "error_count": "Errors",
    "warning_count": "Warnings",
    "issue_type": "Issue",
    "severity": "Priority",
    "market": "Market",
    "state": "State",
    "event_count": "Events",
    "venue_name": "Venue",
    "city": "City",
    "missing_capacity_events": "Events Missing Capacity",
    "invalid_coordinate_events": "Events With Coordinate Issues",
    "canonical_artist_name": "Artist",
    "duplicate_record_count": "Possible Duplicate IDs",
    "sources": "Found In",
    "searched_artist": "Search",
    "api_rows": "Rows Returned",
    "loaded_events": "Events Found",
    "first_event_date": "First Event",
    "last_event_date": "Last Event",
    "top_returned_artist": "Most Common Returned Artist",
    "top_returned_artist_events": "Events for Top Match",
    "started_at": "Started",
    "finished_at": "Finished",
    "status": "Status",
}

DATE_COLUMNS = {
    "started_at",
    "finished_at",
    "last_pulled_at",
    "first_event_date",
    "last_event_date",
}


def _as_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _title_from_token(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unknown"
    text = str(value).strip().replace("_", " ")
    return text.title() if text else "Unknown"


def friendly_source(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unknown Source"

    source = str(value)
    if source.startswith("ticketmaster_artist_"):
        artist = source.replace("ticketmaster_artist_", "")
        return f"Artist Search: {_title_from_token(artist)}"
    return SOURCE_LABELS.get(source, _title_from_token(source))


def friendly_issue(value: Any) -> str:
    if value is None or pd.isna(value):
        return "Unknown Issue"
    return ISSUE_LABELS.get(str(value), _title_from_token(value))


def friendly_frame(
    frame: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    display = frame.copy()
    if columns:
        display = display[[column for column in columns if column in display.columns]]

    for column in ("source", "source_name"):
        if column in display.columns:
            display[column] = display[column].map(friendly_source)
    if "sources" in display.columns:
        display["sources"] = display["sources"].map(friendly_sources)
    if "issue_type" in display.columns:
        display["issue_type"] = display["issue_type"].map(friendly_issue)
    if "severity" in display.columns:
        display["severity"] = display["severity"].map(_title_from_token)
    if "status" in display.columns:
        display["status"] = display["status"].map(
            lambda value: STATUS_LABELS.get(str(value), _title_from_token(value))
        )
    for column in DATE_COLUMNS.intersection(display.columns):
        display[column] = pd.to_datetime(display[column], errors="coerce").dt.strftime("%b %d, %Y")
        display[column] = display[column].fillna("")

    return display.rename(columns=COLUMN_LABELS)


def friendly_sources(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(friendly_source(source) for source in value)
    if value is None or pd.isna(value):
        return "Unknown Source"
    return friendly_source(value)


@st.cache_data(ttl=30)
def get_summary() -> dict[str, Any]:
    return fetch_one(
        """
        SELECT
            COUNT(*)::integer AS event_records,
            COUNT(DISTINCT artist_fingerprint)::integer AS unique_artists,
            COUNT(DISTINCT venue_fingerprint)::integer AS unique_venues,
            COALESCE(ROUND(AVG(quality_score)::numeric, 2), 0) AS avg_quality_score
        FROM live_music_events
        """
    )


@st.cache_data(ttl=30)
def get_quality_by_source() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT *
            FROM vw_data_quality_score_by_source
            ORDER BY avg_quality_score ASC, issue_count DESC
            """
        )
    )


@st.cache_data(ttl=30)
def get_top_issues() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT issue_type, severity, COUNT(*)::integer AS issue_count
            FROM data_quality_issues
            GROUP BY issue_type, severity
            ORDER BY issue_count DESC, issue_type
            """
        )
    )


@st.cache_data(ttl=30)
def get_venue_issues() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT *
            FROM vw_venues_missing_metadata
            ORDER BY event_count DESC, venue_name
            """
        )
    )


@st.cache_data(ttl=30)
def get_artist_duplicates() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT *
            FROM vw_duplicate_artist_candidates
            ORDER BY duplicate_record_count DESC, event_count DESC, canonical_artist_name
            """
        )
    )


@st.cache_data(ttl=30)
def get_artist_search_report() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT
                searched_artist,
                api_rows,
                loaded_events,
                unique_artists,
                unique_venues,
                first_event_date,
                last_event_date,
                avg_quality_score,
                issue_count,
                error_count,
                warning_count,
                top_returned_artist,
                top_returned_artist_events
            FROM vw_artist_search_quality
            ORDER BY loaded_events DESC, searched_artist
            """
        )
    )


@st.cache_data(ttl=30)
def get_top_markets() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT *
            FROM vw_top_markets_by_event_count
            ORDER BY event_count DESC, market
            """
        )
    )


@st.cache_data(ttl=30)
def get_recent_runs() -> pd.DataFrame:
    return _as_frame(
        fetch_all(
            """
            SELECT
                id::text AS id,
                source_name,
                started_at,
                finished_at,
                records_seen,
                records_loaded,
                issue_count,
                status
            FROM ingestion_runs
            ORDER BY started_at DESC
            LIMIT 10
            """
        )
    )


def load_sample_data() -> None:
    load_csv(SAMPLE_CSV, source_name="sample_events", replace=True)
    st.cache_data.clear()


def render_metric_row(summary: dict[str, Any]) -> None:
    event_records = summary.get("event_records", 0) or 0
    unique_artists = summary.get("unique_artists", 0) or 0
    unique_venues = summary.get("unique_venues", 0) or 0
    avg_quality_score = float(summary.get("avg_quality_score", 0) or 0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Events Loaded", f"{event_records:,}")
    col2.metric("Unique Artists", f"{unique_artists:,}")
    col3.metric("Unique Venues", f"{unique_venues:,}")
    col4.metric("Avg Data Health Score", f"{avg_quality_score:.1f}")


def render_dashboard() -> None:
    st.set_page_config(
        page_title="Live Music Data Quality",
        layout="wide",
    )

    st.title("Live Music Data Health Dashboard")
    st.caption("Live event coverage, cleanup priorities, and artist search quality.")

    with st.sidebar:
        st.header("Data Controls")
        if st.button("Load Sample Data", width="stretch"):
            with st.spinner("Loading sample data into PostgreSQL..."):
                load_sample_data()
            st.success("Sample data loaded.")
        if st.button("Refresh Dashboard", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.markdown("**Technical API**")
        st.link_button("Open FastAPI docs", "http://localhost:8000/docs", width="stretch")

    try:
        ping_database()
        summary = get_summary()
    except SQLAlchemyError as exc:
        st.error(f"Database is not reachable yet: {exc}")
        st.stop()

    render_metric_row(summary)

    quality_by_source = get_quality_by_source()
    top_issues = get_top_issues()
    venue_issues = get_venue_issues()
    artist_duplicates = get_artist_duplicates()
    artist_search_report = get_artist_search_report()
    top_markets = get_top_markets()
    recent_runs = get_recent_runs()

    st.subheader("Data Health by Source")
    if quality_by_source.empty:
        st.info("No data loaded yet. Use the sidebar to load the sample CSV.")
    else:
        chart_frame = quality_by_source.assign(
            source_label=quality_by_source["source"].map(friendly_source)
        )
        chart_frame = chart_frame.set_index("source_label")[["avg_quality_score", "issue_count"]]
        chart_frame = chart_frame.rename(
            columns={
                "avg_quality_score": "Data Health Score",
                "issue_count": "Open Issues",
            }
        )
        st.bar_chart(chart_frame)
        st.dataframe(
            friendly_frame(
                quality_by_source,
                [
                    "source",
                    "event_records",
                    "unique_artists",
                    "unique_venues",
                    "avg_quality_score",
                    "issue_count",
                    "error_issues",
                    "warning_issues",
                ],
            ),
            width="stretch",
            hide_index=True,
        )

    issue_col, market_col = st.columns(2)
    with issue_col:
        st.subheader("Most Common Data Problems")
        if top_issues.empty:
            st.info("No issues found.")
        else:
            issue_chart = top_issues.assign(
                issue_label=top_issues["issue_type"].map(friendly_issue)
            )
            issue_chart = issue_chart.set_index("issue_label")["issue_count"]
            issue_chart.name = "Open Issues"
            st.bar_chart(issue_chart)
            st.dataframe(friendly_frame(top_issues), width="stretch", hide_index=True)

    with market_col:
        st.subheader("Busiest Markets")
        if top_markets.empty:
            st.info("No markets found.")
        else:
            market_chart = top_markets.set_index("market")["event_count"]
            market_chart.name = "Events"
            st.bar_chart(market_chart)
            st.dataframe(
                friendly_frame(
                    top_markets,
                    [
                        "market",
                        "state",
                        "event_count",
                        "unique_artist_count",
                        "unique_venue_count",
                        "avg_quality_score",
                    ],
                ),
                width="stretch",
                hide_index=True,
            )

    st.subheader("Venues Needing Cleanup")
    if venue_issues.empty:
        st.success("No venue metadata issues found.")
    else:
        st.dataframe(
            friendly_frame(
                venue_issues,
                [
                    "venue_name",
                    "city",
                    "state",
                    "event_count",
                    "missing_capacity_events",
                    "invalid_coordinate_events",
                    "avg_quality_score",
                ],
            ),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Possible Duplicate Artists")
    if artist_duplicates.empty:
        st.success("No duplicate artist candidates found.")
    else:
        st.dataframe(
            friendly_frame(
                artist_duplicates,
                [
                    "canonical_artist_name",
                    "event_count",
                    "duplicate_record_count",
                    "sources",
                    "avg_quality_score",
                ],
            ),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Artist Search Results")
    if artist_search_report.empty:
        st.info("No artist search pulls found.")
    else:
        artist_chart = artist_search_report.set_index("searched_artist")["loaded_events"]
        artist_chart.name = "Events Found"
        st.bar_chart(artist_chart)
        st.dataframe(friendly_frame(artist_search_report), width="stretch", hide_index=True)

    st.subheader("Recent Data Pulls")
    if recent_runs.empty:
        st.info("No ingestion runs recorded yet.")
    else:
        st.dataframe(
            friendly_frame(
                recent_runs,
                [
                    "source_name",
                    "status",
                    "started_at",
                    "finished_at",
                    "records_seen",
                    "records_loaded",
                    "issue_count",
                ],
            ),
            width="stretch",
            hide_index=True,
        )


if __name__ == "__main__":
    render_dashboard()
