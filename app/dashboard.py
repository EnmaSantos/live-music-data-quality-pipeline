from __future__ import annotations

import io
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from app.config import get_settings

settings = get_settings()
SAMPLE_CSV = Path(__file__).resolve().parents[1] / "data" / "raw" / "sample_events.csv"
PROFILE_FIELDS = [
    "event_id",
    "event_name",
    "event_date",
    "artist_name",
    "venue_name",
    "venue_capacity",
    "latitude",
    "longitude",
    "market",
]


def api_headers(idempotency: bool = False) -> dict[str, str]:
    headers = {
        "X-Data-Referee-Key": settings.data_referee_api_key,
        "X-Data-Referee-Client": settings.data_referee_client_id,
    }
    if idempotency:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    return headers


def request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    with httpx.Client(base_url=settings.data_referee_api_url, timeout=60) as client:
        response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response


def source_bytes() -> tuple[str, bytes] | None:
    uploaded = st.file_uploader("CSV dataset", type=["csv"], help="Maximum 25 MB / 250,000 rows")
    if uploaded:
        return uploaded.name, uploaded.getvalue()
    if st.button("Use the bundled live-event sample"):
        st.session_state["sample_selected"] = True
    if st.session_state.get("sample_selected"):
        return SAMPLE_CSV.name, SAMPLE_CSV.read_bytes()
    return None


def render_profile(profile: dict[str, Any]) -> None:
    metrics = st.columns(4)
    metrics[0].metric("Rows", f"{profile['rows']:,}")
    metrics[1].metric("Columns", profile["columns"])
    metrics[2].metric("Duplicate rows", profile["duplicate_rows"])
    metrics[3].metric("Duplicate rate", f"{profile['duplicate_percentage']:.1f}%")
    st.dataframe(pd.DataFrame(profile["column_profiles"]), width="stretch", hide_index=True)


def render_verdict(summary: dict[str, Any]) -> None:
    verdict = str(summary.get("verdict") or "processing").replace("_", " ").title()
    st.subheader(verdict)
    columns = st.columns(4)
    columns[0].metric("Overall quality", f"{float(summary.get('overall_score') or 0):.1f}/100")
    counts = summary.get("classification_counts") or {}
    columns[1].metric("Accepted", f"{int(counts.get('accepted', 0)):,}")
    columns[2].metric("Quarantined", f"{int(counts.get('quarantined', 0)):,}")
    columns[3].metric("Rejected", f"{int(counts.get('rejected', 0)):,}")

    st.markdown("#### Quality dimensions")
    dimension_frame = pd.DataFrame(
        [
            {"dimension": key.replace("_", " ").title(), "score": value}
            for key, value in (summary.get("dimension_scores") or {}).items()
        ]
    )
    if not dimension_frame.empty:
        st.bar_chart(dimension_frame.set_index("dimension"))

    eligibility = summary.get("use_case_eligibility") or {}
    if eligibility:
        st.markdown("#### Use-case eligibility")
        for use_case, status in eligibility.items():
            icon = {"trusted": "✅", "caution": "⚠️", "blocked": "⛔"}.get(status, "•")
            st.write(f"{icon} **{use_case.replace('_', ' ').title()}** — {status.title()}")


def analyze(filename: str, content: bytes, profile_key: str, mapping: dict[str, str]) -> None:
    dataset_response = request(
        "POST",
        "/v1/datasets",
        headers=api_headers(idempotency=True),
        json={
            "name": filename,
            "source_type": "csv",
            "retention_hours": 24,
            "column_mapping": mapping,
        },
    )
    dataset_id = dataset_response.json()["id"]
    request(
        "PUT",
        f"/v1/datasets/{dataset_id}/source-file",
        headers=api_headers(idempotency=True),
        files={"file": (filename, content, "text/csv")},
    )
    profile = request(
        "GET", f"/v1/datasets/{dataset_id}/profile", headers=api_headers()
    ).json()
    run = request(
        "POST",
        f"/v1/datasets/{dataset_id}/quality-runs",
        headers=api_headers(idempotency=True),
        json={"profile_key": profile_key, "profile_version": "1.0.0"},
    ).json()
    st.session_state.update(
        dataset_id=dataset_id,
        quality_run_id=run["id"],
        dataset_profile=profile,
        quality_summary=None,
    )


def poll_run(run_id: str, wait_seconds: int = 20) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = request("GET", f"/v1/quality-runs/{run_id}", headers=api_headers()).json()
        if status["status"] in {"completed", "failed", "dead_letter"}:
            return status
        time.sleep(1)
    return status


def main() -> None:
    st.set_page_config(page_title="Data Referee", page_icon="⚖️", layout="wide")
    st.title("Data Referee")
    st.caption("Find out whether your data is trustworthy enough for the job you need to do.")
    st.warning(
        "Do not upload personal, medical, financial, confidential, or otherwise sensitive data. "
        "Public upload details are deleted after 24 hours."
    )

    with st.sidebar:
        st.header("How it works")
        st.write("1. Upload a CSV")
        st.write("2. Select a quality profile")
        st.write("3. Review the verdict")
        st.write("4. Export accepted or quarantined rows")
        st.link_button("Open API documentation", f"{settings.data_referee_api_url}/docs")

    source = source_bytes()
    if not source:
        st.info("Upload a CSV or use the sample dataset to begin.")
        return
    filename, content = source
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        st.error("This file is larger than the configured 25 MB limit.")
        return

    try:
        preview = pd.read_csv(io.BytesIO(content), nrows=20)
    except Exception as exc:
        st.error(f"The CSV could not be parsed: {exc}")
        return
    st.subheader("Preview")
    st.dataframe(preview, width="stretch", hide_index=True)

    profile_key = st.selectbox(
        "Quality profile",
        ["live-events", "generic"],
        format_func=lambda value: value.replace("-", " ").title(),
    )
    mapping: dict[str, str] = {}
    if profile_key == "live-events":
        st.markdown("#### Column mapping")
        available = ["Not mapped", *preview.columns.tolist()]
        mapping_columns = st.columns(3)
        for index, field in enumerate(PROFILE_FIELDS):
            default_index = available.index(field) if field in available else 0
            selected = mapping_columns[index % 3].selectbox(
                field.replace("_", " ").title(),
                available,
                index=default_index,
                key=f"mapping-{field}",
            )
            if selected != "Not mapped":
                mapping[field] = selected

    if st.button("Run Data Referee", type="primary", width="stretch"):
        try:
            with st.spinner("Uploading, sealing, and queuing the evaluation..."):
                analyze(filename, content, profile_key, mapping)
        except httpx.HTTPStatusError as exc:
            st.error(f"Data Referee rejected the request: {exc.response.text}")
            return
        except httpx.HTTPError as exc:
            st.error(f"Data Referee API is unavailable: {exc}")
            return

    run_id = st.session_state.get("quality_run_id")
    dataset_profile = st.session_state.get("dataset_profile")
    if dataset_profile:
        st.divider()
        st.subheader("Dataset profile")
        render_profile(dataset_profile)
    if not run_id:
        return

    try:
        with st.spinner("Evaluating records..."):
            status = poll_run(run_id)
    except httpx.HTTPError as exc:
        st.error(f"Could not read evaluation status: {exc}")
        return
    st.progress(float(status.get("progress", 0)))
    st.caption(
        f"Run {run_id} · {status.get('records_processed', 0):,} / "
        f"{status.get('records_total', 0):,} records · {status.get('status', 'unknown')}"
    )
    if status.get("status") != "completed":
        if st.button("Refresh evaluation status"):
            st.rerun()
        if status.get("last_error"):
            st.error(status["last_error"])
        return

    summary = request(
        "GET", f"/v1/quality-runs/{run_id}/summary", headers=api_headers()
    ).json()
    st.divider()
    render_verdict(summary)

    st.markdown("#### Record results")
    results = request(
        "GET",
        f"/v1/quality-runs/{run_id}/record-results?limit=250",
        headers=api_headers(),
    ).json()
    display_rows = [
        {
            "Record": item["external_record_id"],
            "Score": item["score"],
            "Classification": item["classification"].title(),
            "Warnings": item["warning_count"],
            "Errors": item["error_count"],
        }
        for item in results["items"]
    ]
    st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True)

    st.markdown("#### Exports")
    columns = st.columns(3)
    for column, classification in zip(columns, ["accepted", "quarantined", "rejected"]):
        export = request(
            "GET",
            f"/v1/quality-runs/{run_id}/exports/{classification}.csv",
            headers=api_headers(),
        )
        column.download_button(
            f"Download {classification}",
            export.content,
            file_name=f"{classification}-{run_id}.csv",
            mime="text/csv",
            width="stretch",
        )


if __name__ == "__main__":
    main()
