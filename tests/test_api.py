from fastapi.testclient import TestClient

import app.main as main


def test_health_endpoint_reports_ok(monkeypatch) -> None:
    monkeypatch.setattr(main, "ping_database", lambda: True)

    client = TestClient(main.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


def test_data_quality_report_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "fetch_one",
        lambda query: {
            "event_records": 100,
            "unique_artists": 10,
            "unique_venues": 8,
            "avg_quality_score": 91.2,
        },
    )

    def fake_fetch_all(query, params=None):
        if "vw_data_quality_score_by_source" in query:
            return [{"source": "ticketmaster_csv", "event_records": 50, "issue_count": 3}]
        if "data_quality_issues" in query:
            return [{"issue_type": "missing_venue_capacity", "severity": "warning"}]
        return [{"id": "run-1", "status": "completed"}]

    monkeypatch.setattr(main, "fetch_all", fake_fetch_all)

    client = TestClient(main.app)
    response = client.get("/data-quality-report")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["event_records"] == 100
    assert body["score_by_source"][0]["source"] == "ticketmaster_csv"
    assert body["top_issues"][0]["issue_type"] == "missing_venue_capacity"
    assert body["recent_ingestion_runs"][0]["status"] == "completed"
