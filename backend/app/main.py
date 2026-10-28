"""FastAPI service: REST + WebSocket over the headless pipeline.

Run (binds 127.0.0.1:8000 by default; refuses to start without MD_API_TOKEN):
    .venv/bin/python -m app.main
    .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import protected, public
from app.api.security import Guard, RateLimiter, RedactedJSONResponse
from app.config import Settings
from app.executor import Executor, SimulatedExecutor
from app.providers import CloudAPIProvider, LanguageModelProvider, LocalInferenceProvider, NVIDIAInferenceProvider
from app.security import MAX_RAW_CHARS, install_log_redaction
from app.tasks import TaskManager
from app.tokenizer import Tokenizer
from app.validation import SafetyValidator, default_world
from app.websocket.handlers import ConnectionSlots, pipeline_ws, telemetry_ws

log = logging.getLogger("munder_difflin")
MAX_BODY_BYTES = MAX_RAW_CHARS * 2


def default_providers() -> list[LanguageModelProvider]:
    return [CloudAPIProvider(), LocalInferenceProvider(), NVIDIAInferenceProvider()]


def create_app(
    settings: Settings | None = None,
    providers: Sequence[LanguageModelProvider] | None = None,
    executor: Executor | None = None,
    tokenizer: Tokenizer | None = None,
) -> FastAPI:
    settings = (settings or Settings.from_env()).validate()  # SEC S5: refuse to start misconfigured
    install_log_redaction()
    guard = Guard(settings.api_token, settings.auth_failures_per_min)
    response_class = type("AppJSONResponse", (RedactedJSONResponse,), {"guard": guard})

    app = FastAPI(
        title="Munder Difflin backend",
        default_response_class=response_class,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
    )
    app.state.settings = settings
    app.state.guard = guard
    app.state.task_limiter = RateLimiter(settings.task_rate_per_min)
    app.state.ws_slots = ConnectionSlots(settings.ws_max_connections)
    app.state.manager = TaskManager(
        SafetyValidator(default_world()),
        executor or SimulatedExecutor(),
        default_providers() if providers is None else providers,
        tokenizer,
        settings.max_tasks_kept,
        guard.secrets,
    )

    # SEC-007: explicit origins; credentials off (auth is a bearer header, not cookies).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return response_class({"detail": "request body too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return response_class({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Never echo the submitted input back (it can be huge, or contain what the client should not see).
        errors = [{"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "")} for e in exc.errors()][:10]
        return response_class({"detail": "invalid request", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        log.error("unhandled %s on %s", type(exc).__name__, request.url.path)
        return response_class({"detail": "internal error"}, status_code=500)

    app.include_router(public)
    app.include_router(protected)
    app.add_api_websocket_route("/ws/pipeline", pipeline_ws)
    app.add_api_websocket_route("/ws/telemetry", telemetry_ws)
    log.info("providers on this server: %s", ", ".join(p.name for p in app.state.manager.providers.values()) or "none")
    return app


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, server_header=False)


if __name__ == "__main__":
    main()
