"""FastAPI app (spec sections 9, 12, 27, 28, 30).

Run with the app factory (nothing is created at import time):

    uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1

--workers 1 matters: the store and job queue live inside this one process.

Needs a reachable PostgreSQL (DATABASE_URL). Tables are created at startup.

Endpoints so far: /health, POST /deploy, GET /apps, GET /apps/{app_name}.
Logs and DELETE arrive in Phase 6, auth and CORS in Phase 7.
"""
import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .db import make_engine
from .jobs import JobRunner
from .models import (
    AppDetail,
    AppSummary,
    DeployAccepted,
    DeploymentOut,
    DeployRequest,
    ErrorCode,
    GoldenPath,
    canonical_repo_url,
    public_deployment_id,
)
from .pipeline import run_deployment, run_guarded
from .store import ApplicationRecord, DeploymentRecord, GoldenPathConflict, Store

logger = logging.getLogger(__name__)

Pipeline = Callable[[uuid.UUID, Store], None]


class ApiError(Exception):
    """Non-validation API errors, returned as {"error_code", "message"}."""

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        self.status_code, self.code, self.message = status_code, code, message


def _deployment_out(d: DeploymentRecord) -> DeploymentOut:
    return DeploymentOut(
        deployment_id=public_deployment_id(d.id),
        status=d.status,
        source_revision=d.source_revision,
        image_tag=d.image_tag,
        gitops_commit=d.gitops_commit,
        error_code=d.error_code,
        error_message=d.error_message,
        created_at=d.created_at,
        completed_at=d.completed_at,
    )


def _summary(a: ApplicationRecord) -> dict:
    return dict(
        name=a.name,
        golden_path=a.golden_path,
        repository=a.repository_url,
        status=a.current_status,
        live_url=a.live_url,
        updated_at=a.updated_at,
    )


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    pipeline: Pipeline | None = None,
) -> FastAPI:
    """`store` and `pipeline` are injectable so tests can control timing."""
    settings = settings or get_settings()
    pipeline = pipeline or partial(run_deployment, settings=settings)
    owns_store = store is None
    if store is None:
        store = Store(make_engine(settings.database_url.get_secret_value()))
    runner = JobRunner(workers=settings.job_workers)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Fail fast: if PostgreSQL is unreachable the app refuses to start
        # (and systemd shows why) instead of limping along returning 500s.
        store.create_schema()
        orphaned = store.fail_orphaned()
        if orphaned:
            logger.warning("marked %d in-progress deployment(s) failed after restart", orphaned)
        yield
        runner.shutdown()
        if owns_store:
            store.dispose()

    app = FastAPI(title="RowdyHacks IDP control plane", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.runner = runner  # exposed so tests can wait for in-flight jobs

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": exc.code.value, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Same 422 shape as FastAPI's default, minus the echoed `input`: we
        # reject secrets (tokens in URLs, env values), so never repeat them back.
        detail = [{"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/deploy", status_code=202, response_model=DeployAccepted)
    def deploy(req: DeployRequest) -> DeployAccepted:
        # Request-level validation already happened (422 before we get here).
        # Everything below only records intent and queues work: no clone,
        # build, Git or Kubernetes call may happen in this request (spec 12).
        try:
            application, deployment = store.create_deployment(
                name=req.name,
                golden_path=GoldenPath(req.golden_path),
                repository_url=canonical_repo_url(req.repository),
                namespace=f"app-{req.name}",
                live_url=f"https://{req.name}.{settings.platform_domain}",
            )
        except GoldenPathConflict as exc:
            raise ApiError(409, ErrorCode.GOLDEN_PATH_CONFLICT, str(exc)) from exc

        runner.submit(run_guarded, pipeline, deployment.id, store)
        return DeployAccepted(
            deployment_id=public_deployment_id(deployment.id),
            app_name=application.name,
            status=deployment.status,
        )

    @app.get("/apps", response_model=list[AppSummary])
    def list_apps() -> list[AppSummary]:
        return [AppSummary(**_summary(a)) for a in store.list_applications()]

    @app.get("/apps/{app_name}", response_model=AppDetail)
    def get_app(app_name: str) -> AppDetail:
        application = store.get_application(app_name)
        if application is None:
            raise ApiError(404, ErrorCode.APP_NOT_FOUND, f"No application named '{app_name}'")
        latest = store.get_latest_deployment(application.id)
        return AppDetail(
            **_summary(application),
            namespace=application.namespace,
            latest_deployment=_deployment_out(latest) if latest else None,
        )

    return app
