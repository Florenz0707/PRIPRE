"""Exercise the public API contract without external services."""

from fastapi.testclient import TestClient
from pripre.api import create_app


def test_health_reports_scaffold_without_claiming_market_readiness() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "pripre-api",
        "version": "0.1.0",
        "stage": "scaffold",
    }


def test_unknown_api_route_does_not_return_placeholder_success() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/matrix")
    assert response.status_code == 404
