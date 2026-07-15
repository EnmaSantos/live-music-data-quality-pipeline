"""Start the correct hosted web process from the shared Docker image."""

import os

from app.initialize import initialize


def command_for_service(service_name: str, port: str) -> list[str]:
    normalized = service_name.lower()
    if "worker" in normalized:
        return ["python", "-m", "app.worker"]
    if "app" in normalized or "dashboard" in normalized:
        return [
            "streamlit",
            "run",
            "app/dashboard.py",
            "--server.address",
            "0.0.0.0",
            "--server.port",
            port,
            "--server.headless",
            "true",
        ]
    return ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port]


def main() -> None:
    initialize()
    command = command_for_service(
        os.getenv("RENDER_SERVICE_NAME", "api"),
        os.getenv("PORT", "8000"),
    )
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
