from app.start import command_for_service


def test_api_service_command() -> None:
    command = command_for_service("live-music-quality-api", "10000")
    assert command[:2] == ["uvicorn", "app.main:app"]
    assert command[-1] == "10000"


def test_dashboard_service_command() -> None:
    command = command_for_service("live-music-quality-dashboard", "10000")
    assert command[:3] == ["streamlit", "run", "app/dashboard.py"]
    assert "10000" in command
