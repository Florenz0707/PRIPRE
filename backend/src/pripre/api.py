"""HTTP application boundary; market data and prediction are not connected yet."""

from importlib.metadata import version
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["pripre-api"] = "pripre-api"
    version: str
    stage: Literal["scaffold"] = "scaffold"


def create_app() -> FastAPI:
    """Create an isolated application for serving and testing."""
    app = FastAPI(title="PRIPRE API", version=version("pripre"))

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Report process health, not market data readiness."""
        return HealthResponse(version=app.version)

    return app


app = create_app()
