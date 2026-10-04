"""In-memory persistence for Phase 1.

Phase 2 replaces this module with PostgreSQL (`applications` + `deployments`,
spec section 14) behind the same method names, so main.py and pipeline.py do
not change. The record fields below already mirror the spec's columns.

All methods are thread-safe: the API threads and the pipeline worker thread
share one Store.
"""
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .models import (
    IN_PROGRESS,
    DeploymentStatus,
    ErrorCode,
    GoldenPath,
    transition_allowed,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ApplicationRecord:
    id: uuid.UUID
    name: str
    golden_path: GoldenPath
    repository_url: str
    namespace: str
    live_url: str
    current_status: DeploymentStatus
    created_at: datetime
    updated_at: datetime


@dataclass
class DeploymentRecord:
    id: uuid.UUID
    application_id: uuid.UUID
    status: DeploymentStatus
    created_at: datetime
    updated_at: datetime
    source_revision: str | None = None
    image_tag: str | None = None  # NULL for static apps
    gitops_commit: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None


class GoldenPathConflict(Exception):
    """Redeploy attempted with a different Golden Path than the app already has."""


class InvalidTransition(Exception):
    pass


class DeploymentNotFound(Exception):
    pass


# Fields the pipeline may record on a deployment as it learns them.
_SETTABLE = {"source_revision", "image_tag", "gitops_commit", "error_code", "error_message"}


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._apps: dict[str, ApplicationRecord] = {}  # by name
        self._deployments: dict[uuid.UUID, DeploymentRecord] = {}
        self._by_app: dict[uuid.UUID, list[uuid.UUID]] = {}  # creation order

    # ---- reads (return copies so callers never see half-written state) ----

    def get_application(self, name: str) -> ApplicationRecord | None:
        with self._lock:
            rec = self._apps.get(name)
            return replace(rec) if rec else None

    def list_applications(self) -> list[ApplicationRecord]:
        with self._lock:
            recs = [replace(r) for r in self._apps.values()]
        return sorted(recs, key=lambda r: (-r.updated_at.timestamp(), r.name))

    def get_deployment(self, dep_id: uuid.UUID) -> DeploymentRecord | None:
        with self._lock:
            rec = self._deployments.get(dep_id)
            return replace(rec) if rec else None

    def get_latest_deployment(self, app_id: uuid.UUID) -> DeploymentRecord | None:
        with self._lock:
            ids = self._by_app.get(app_id)
            return replace(self._deployments[ids[-1]]) if ids else None

    # ---- writes ----

    def create_deployment(
        self,
        *,
        name: str,
        golden_path: GoldenPath,
        repository_url: str,
        namespace: str,
        live_url: str,
    ) -> tuple[ApplicationRecord, DeploymentRecord]:
        """Create the app if new, then a new PENDING deployment attempt (spec section 9)."""
        with self._lock:
            now = _now()
            app = self._apps.get(name)
            if app is None:
                app = ApplicationRecord(
                    id=uuid.uuid4(),
                    name=name,
                    golden_path=golden_path,
                    repository_url=repository_url,
                    namespace=namespace,
                    live_url=live_url,
                    current_status=DeploymentStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                )
                self._apps[name] = app
                self._by_app[app.id] = []
            else:
                if app.golden_path != golden_path:
                    raise GoldenPathConflict(
                        f"'{name}' already exists as a {app.golden_path.value} app; "
                        "delete it before deploying it with a different Golden Path"
                    )
                app.repository_url = repository_url
                app.current_status = DeploymentStatus.PENDING
                app.updated_at = now

            dep = DeploymentRecord(
                id=uuid.uuid4(),
                application_id=app.id,
                status=DeploymentStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
            self._deployments[dep.id] = dep
            self._by_app[app.id].append(dep.id)
            return replace(app), replace(dep)

    def update_fields(self, dep_id: uuid.UUID, **fields: str | None) -> None:
        """Record facts (source SHA, image tag, ...) without changing status."""
        bad = set(fields) - _SETTABLE
        if bad:
            raise ValueError(f"cannot set {sorted(bad)}")
        with self._lock:
            dep = self._require(dep_id)
            for key, value in fields.items():
                setattr(dep, key, value)
            dep.updated_at = _now()

    def transition(self, dep_id: uuid.UUID, new: DeploymentStatus, **fields: str | None) -> None:
        """Move a deployment along the state machine and mirror it onto the app."""
        with self._lock:
            dep = self._require(dep_id)
            app = self._app_of(dep)
            if not transition_allowed(app.golden_path, dep.status, new):
                raise InvalidTransition(
                    f"{app.golden_path.value}: {dep.status.value} -> {new.value} is not allowed"
                )
            self._apply(dep, app, new, fields)

    def fail(self, dep_id: uuid.UUID, code: ErrorCode, message: str) -> None:
        """Platform-error path: FAILED from any in-progress state (spec section 25)."""
        with self._lock:
            dep = self._require(dep_id)
            if dep.status not in IN_PROGRESS:
                return  # already terminal; never overwrite a RUNNING/FAILED outcome
            self._apply(
                dep,
                self._app_of(dep),
                DeploymentStatus.FAILED,
                {"error_code": code.value, "error_message": message},
            )

    # ---- internals (caller holds the lock) ----

    def _require(self, dep_id: uuid.UUID) -> DeploymentRecord:
        dep = self._deployments.get(dep_id)
        if dep is None:
            raise DeploymentNotFound(str(dep_id))
        return dep

    def _app_of(self, dep: DeploymentRecord) -> ApplicationRecord:
        return next(a for a in self._apps.values() if a.id == dep.application_id)

    def _apply(self, dep, app, new, fields) -> None:
        bad = set(fields) - _SETTABLE
        if bad:
            raise ValueError(f"cannot set {sorted(bad)}")
        now = _now()
        for key, value in fields.items():
            setattr(dep, key, value)
        dep.status = new
        dep.updated_at = now
        if new in (DeploymentStatus.RUNNING, DeploymentStatus.FAILED) and dep.completed_at is None:
            dep.completed_at = now
        # The app's status always mirrors its LATEST deployment.
        if self._by_app[app.id][-1] == dep.id:
            app.current_status = new
            app.updated_at = now
