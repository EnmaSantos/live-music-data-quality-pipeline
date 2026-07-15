from app.start import command_for_service


def test_api_service_command() -> None:
    command = command_for_service("data-referee-api", "10000")
    assert command[:2] == ["uvicorn", "app.main:app"]
    assert command[-1] == "10000"


def test_dashboard_service_command() -> None:
    command = command_for_service("data-referee-app", "10000")
    assert command[:3] == ["streamlit", "run", "app/dashboard.py"]
    assert "10000" in command


def test_worker_service_command() -> None:
    assert command_for_service("data-referee-worker", "10000") == [
        "python",
        "-m",
        "app.worker",
    ]
