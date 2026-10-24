"""Exercise the public API contract without external services."""

from pathlib import Path

from fastapi.testclient import TestClient
from pripre.api import create_app


def test_health_reports_process_health_without_claiming_market_readiness() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "pripre-api",
        "version": "0.1.0",
        "stage": "research",
    }


def test_unknown_api_route_does_not_return_placeholder_success() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/not-implemented")
    assert response.status_code == 404


def test_disabled_matrix_never_claims_live_probabilities() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/matrix")
    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert response.json()["probabilities"] is None


def test_missing_research_report_is_explicit(tmp_path: Path) -> None:

    from pripre.config import AppConfig, HistoryConfig

    config = AppConfig(history=HistoryConfig(data_dir=tmp_path))
    with TestClient(create_app(config)) as client:
        assert client.get("/api/research").status_code == 404


def test_corrupt_research_report_returns_a_recoverable_error(tmp_path: Path) -> None:
    from pripre.config import AppConfig, HistoryConfig

    path = tmp_path / "research" / "report.json"
    path.parent.mkdir()
    path.write_text("{broken")
    with TestClient(create_app(AppConfig(history=HistoryConfig(data_dir=tmp_path)))) as client:
        assert client.get("/api/research").status_code == 503
