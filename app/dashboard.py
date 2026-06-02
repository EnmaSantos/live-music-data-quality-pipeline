from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from app.db import fetch_all, fetch_one, ping_database
from app.ingestion.pipeline import load_csv

SAMPLE_CSV = Path("data/raw/sample_events.csv")


def _as_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


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
    col4.metric("Avg Quality Score", f"{avg_quality_score:.1f}")


def render_dashboard() -> None:
    st.set_page_config(
        page_title="Live Music Data Quality",
        layout="wide",
    )

    st.title("Live Music Data Quality Pipeline")
    st.caption("PostgreSQL-backed monitoring for messy event, artist, venue, and market data.")

    with st.sidebar:
        st.header("Pipeline Controls")
        if st.button("Load sample CSV", width="stretch"):
            with st.spinner("Loading sample data into PostgreSQL..."):
                load_sample_data()
            st.success("Sample data loaded.")
        if st.button("Refresh dashboard", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.markdown("**API docs**")
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

    st.subheader("Source Quality")
    if quality_by_source.empty:
        st.info("No data loaded yet. Use the sidebar to load the sample CSV.")
    else:
        chart_frame = quality_by_source.set_index("source")[["avg_quality_score", "issue_count"]]
        st.bar_chart(chart_frame)
        st.dataframe(quality_by_source, width="stretch", hide_index=True)

    issue_col, market_col = st.columns(2)
    with issue_col:
        st.subheader("Top Quality Issues")
        if top_issues.empty:
            st.info("No issues found.")
        else:
            st.bar_chart(top_issues.set_index("issue_type")["issue_count"])
            st.dataframe(top_issues, width="stretch", hide_index=True)

    with market_col:
        st.subheader("Top Markets")
        if top_markets.empty:
            st.info("No markets found.")
        else:
            st.bar_chart(top_markets.set_index("market")["event_count"])
            st.dataframe(top_markets, width="stretch", hide_index=True)

    st.subheader("Venues Missing Metadata")
    if venue_issues.empty:
        st.success("No venue metadata issues found.")
    else:
        st.dataframe(venue_issues, width="stretch", hide_index=True)

    st.subheader("Duplicate Artist Candidates")
    if artist_duplicates.empty:
        st.success("No duplicate artist candidates found.")
    else:
        st.dataframe(artist_duplicates, width="stretch", hide_index=True)

    st.subheader("Artist Search Quality")
    if artist_search_report.empty:
        st.info("No artist search pulls found.")
    else:
        st.bar_chart(artist_search_report.set_index("searched_artist")["loaded_events"])
        st.dataframe(artist_search_report, width="stretch", hide_index=True)

    st.subheader("Recent Ingestion Runs")
    if recent_runs.empty:
        st.info("No ingestion runs recorded yet.")
    else:
        st.dataframe(recent_runs, width="stretch", hide_index=True)


if __name__ == "__main__":
    render_dashboard()
