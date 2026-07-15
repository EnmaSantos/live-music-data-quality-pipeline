from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.referee import router as referee_router
from app.config import get_settings
from app.db import ping_database

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Explainable dataset profiling, validation, classification, and quality exports.",
    version="1.0.0",
)
app.include_router(referee_router)


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def health_ready() -> dict[str, str]:
    try:
        ping_database()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is not ready.") from exc
    return {"status": "ready"}


@app.get("/health", include_in_schema=False)
def health_compatibility() -> dict[str, str]:
    return health_ready()
