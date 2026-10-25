"""HTTP and WebSocket composition root; external data use is explicit configuration."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from pripre.backtesting.queries import filtered_report, replay_detail, replay_page
from pripre.config import AppConfig, RuntimeConfig, load_config
from pripre.data.binance import BinanceSource
from pripre.data.http import DownloadBudget, PublicHTTP
from pripre.data.source import SourceRegistry
from pripre.journal import PredictionJournal
from pripre.runtime import MatrixRuntime


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["pripre-api"] = "pripre-api"
    version: str
    stage: Literal["research"] = "research"


def create_app(config: AppConfig | None = None, runtime: MatrixRuntime | None = None) -> FastAPI:
    settings = config or load_config(
        Path(os.environ["PRIPRE_CONFIG"]) if "PRIPRE_CONFIG" in os.environ else None
    )
    if "PRIPRE_LIVE_ENABLED" in os.environ:
        runtime_values = settings.runtime.model_dump()
        runtime_values["live_enabled"] = os.environ["PRIPRE_LIVE_ENABLED"]
        settings = settings.model_copy(
            update={"runtime": RuntimeConfig.model_validate(runtime_values)}
        )
    if runtime is None:
        source = None
        journal = None
        clock_sync = None
        if settings.runtime.live_enabled:
            registry = SourceRegistry()
            binance = BinanceSource(
                settings.instrument, PublicHTTP(DownloadBudget(1_000_000, 64 * 1048576))
            )
            registry.register(binance, settings.instrument, settings.source.symbol)
            clock_sync = binance.server_time
            source, _ = registry.resolve(
                settings.instrument.id, settings.source.provider, live=True
            )
            journal = PredictionJournal(settings.history.data_dir / "live" / "predictions.sqlite")
        runtime = MatrixRuntime(settings, source=source, journal=journal, clock_sync=clock_sync)
    service = runtime

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(title="PRIPRE API", version=version("pripre"), lifespan=lifespan)
    app.state.runtime = service

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(version=app.version)

    @app.get("/api/config")
    def configuration() -> dict[str, object]:
        return settings.model_dump(mode="json")

    @app.get("/api/matrix")
    async def matrix() -> dict[str, object]:
        return service.for_delivery(service.snapshot)

    @app.get("/api/research")
    def research(start: date | None = None, end: date | None = None) -> dict[str, object]:
        if start is not None or end is not None:
            try:
                return filtered_report(settings.history.data_dir, start, end)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            except OSError as exc:
                raise HTTPException(503, "Replay evidence is unavailable; rerun backtest") from exc
        path = settings.history.data_dir / "research" / "report.json"
        if not path.exists():
            raise HTTPException(404, "Research report is not available; run the backtest command")
        try:
            result: dict[str, object] = json.loads(path.read_text())
            if not isinstance(result, dict) or "models" not in result:
                raise ValueError("invalid research report")
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Research report could not be read") from exc
        return result

    @app.get("/api/experiments")
    def experiments() -> dict[str, object]:
        path = settings.history.data_dir / "research" / "experiments.json"
        try:
            result: dict[str, object] = json.loads(path.read_text())
            if not isinstance(result, dict) or "variants" not in result:
                raise ValueError("invalid experiment report")
            return result
        except FileNotFoundError as exc:
            raise HTTPException(404, "Run the experiments command first") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(503, "Experiment report could not be read") from exc

    @app.get("/api/replay")
    def replay(
        start: date | None = None,
        end: date | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> dict[str, object]:
        try:
            return replay_page(settings.history.data_dir, start, end, offset, limit)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Replay evidence is unavailable; rerun backtest") from exc

    @app.get("/api/replay/{timestamp_us}")
    def replay_prediction(
        timestamp_us: int, model: str = "conditional-calibrated"
    ) -> dict[str, object]:
        try:
            return replay_detail(settings.history.data_dir, timestamp_us, model)
        except KeyError as exc:
            raise HTTPException(404, "Prediction not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Replay evidence is unavailable; rerun backtest") from exc

    @app.websocket("/api/stream")
    async def stream(socket: WebSocket) -> None:
        try:
            queue = service.subscribe()
        except ValueError:
            await socket.accept()
            await socket.close(code=1013, reason="Maximum clients reached")
            return
        await socket.accept()
        try:
            while True:
                await socket.send_json(service.for_delivery(await queue.get()))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            service.unsubscribe(queue)

    return app


app = create_app()
