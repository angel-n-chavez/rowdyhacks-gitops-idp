"""PostgreSQL-backed persistence (Phase 2; spec sections 13-14).

Same public interface as the Phase 1 in-memory store, so main.py and
pipeline.py did not change. Methods return plain dataclass records (copies,
not live ORM objects), so callers never see half-written state and never
need an open session.

Concurrency. Phase 1 used one process-wide lock. Here PostgreSQL does that
job, because API threads and the pipeline worker thread all write at once:

  * create_deployment: INSERT ... ON CONFLICT DO NOTHING, then
    SELECT ... FOR UPDATE on the application row. Two simultaneous first
    deploys of the same name end up as one application with two attempts,
    never a unique-violation error, and attempts of one app are serialized.
  * transition / fail / update_fields: lock the deployment row, then the
    application row (FOR UPDATE), so the read-check-write is atomic.

  Lock order is always  application -> (new) deployment  when creating and
  deployment -> application  when updating. Creating never waits on an
  existing deployment row, so the two orders cannot deadlock.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .db import ApplicationRow, DeploymentRow, create_schema
from .models import (
    IN_PROGRESS,
    DeploymentStatus,
    ErrorCode,
    GoldenPath,
    transition_allowed,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    # PostgreSQL hands timestamptz back in the *session's* time zone. Pin to
    # UTC so API output is identical no matter how the server is configured.
    return value.astimezone(timezone.utc) if value is not None else None


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
    source_revision: str | None = None  # developer source commit
    image_tag: str | None = None  # image built from it; NULL for static apps
    gitops_commit: str | None = None  # commit holding the rendered desired state
    error_code: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None


class GoldenPathConflict(Exception):
    """Redeploy attempted with a different Golden Path than the app already has."""


class InvalidTransition(Exception):
    pass


class DeploymentNotFound(Exception):
    pass


def _app_record(row: ApplicationRow) -> ApplicationRecord:
    return ApplicationRecord(
        id=row.id,
        name=row.name,
        golden_path=GoldenPath(row.golden_path),
        repository_url=row.repository_url,
        namespace=row.namespace,
        live_url=row.live_url,
        current_status=DeploymentStatus(row.current_status),
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _dep_record(row: DeploymentRow) -> DeploymentRecord:
    return DeploymentRecord(
        id=row.id,
        application_id=row.application_id,
        status=DeploymentStatus(row.status),
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        source_revision=row.source_revision,
        image_tag=row.image_tag,
        gitops_commit=row.gitops_commit,
        error_code=row.error_code,
        error_message=row.error_message,
        completed_at=_utc(row.completed_at),
    )


# Fields the pipeline may record on a deployment as it learns them.
_SETTABLE = {"source_revision", "image_tag", "gitops_commit", "error_code", "error_message"}

_RESTART_MESSAGE = (
    "The control plane restarted while this deployment was in progress. "
    "Deploy again to retry."
)


class Store:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        # expire_on_commit=False: rows stay readable after the transaction
        # ends, which is how we convert them into records.
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    # ---- lifecycle ----

    def create_schema(self) -> None:
        create_schema(self._engine)

    def dispose(self) -> None:
        self._engine.dispose()

    def fail_orphaned(self) -> int:
        """Fail every deployment that was in progress when the process stopped.

        Jobs live in this process's memory, so after a restart nothing is
        working on them any more; left alone they would show `validating` (or
        similar) forever and the portal would poll them forever. RUNNING and
        CRASHING are observed states, not work in flight, so they are kept.
        Safe because the control plane runs as a single process (--workers 1).
        """
        with self._sessions() as s:
            ids = s.scalars(
                select(DeploymentRow.id).where(
                    DeploymentRow.status.in_([st.value for st in IN_PROGRESS])
                )
            ).all()
        for dep_id in ids:
            self.fail(dep_id, ErrorCode.INTERNAL_ERROR, _RESTART_MESSAGE)
        return len(ids)

    # ---- reads ----

    def get_application(self, name: str) -> ApplicationRecord | None:
        with self._sessions() as s:
            row = s.scalar(select(ApplicationRow).where(ApplicationRow.name == name))
            return _app_record(row) if row else None

    def get_application_by_id(self, app_id: uuid.UUID) -> ApplicationRecord | None:
        with self._sessions() as s:
            row = s.get(ApplicationRow, app_id)
            return _app_record(row) if row else None

    def list_applications(self) -> list[ApplicationRecord]:
        with self._sessions() as s:
            rows = s.scalars(
                select(ApplicationRow).order_by(ApplicationRow.updated_at.desc(), ApplicationRow.name)
            ).all()
            return [_app_record(r) for r in rows]

    def get_deployment(self, dep_id: uuid.UUID) -> DeploymentRecord | None:
        with self._sessions() as s:
            row = s.get(DeploymentRow, dep_id)
            return _dep_record(row) if row else None

    def get_latest_deployment(self, app_id: uuid.UUID) -> DeploymentRecord | None:
        with self._sessions() as s:
            return _dep_record_or_none(_latest_row(s, app_id))

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
        with self._sessions.begin() as s:
            created = _now()
            inserted = s.execute(
                pg_insert(ApplicationRow)
                .values(
                    id=uuid.uuid4(),
                    name=name,
                    golden_path=golden_path.value,
                    repository_url=repository_url,
                    namespace=namespace,
                    live_url=live_url,
                    current_status=DeploymentStatus.PENDING.value,
                    created_at=created,
                    updated_at=created,
                )
                .on_conflict_do_nothing(index_elements=["name"])
            ).rowcount == 1

            # Lock the app row. From here until commit, other deploys of this
            # same app queue up behind us.
            app = s.scalars(
                select(ApplicationRow).where(ApplicationRow.name == name).with_for_update()
            ).one()

            # Timestamp taken while holding the lock, so attempts of one app
            # get strictly increasing created_at in lock order ("latest").
            now = _now()
            if not inserted:
                if app.golden_path != golden_path.value:
                    raise GoldenPathConflict(
                        f"'{name}' already exists as a {app.golden_path} app; "
                        "delete it before deploying it with a different Golden Path"
                    )
                app.repository_url = repository_url
                app.current_status = DeploymentStatus.PENDING.value
                app.updated_at = now

            dep = DeploymentRow(
                id=uuid.uuid4(),
                application_id=app.id,
                status=DeploymentStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            s.add(dep)
            s.flush()
            return _app_record(app), _dep_record(dep)

    def update_fields(self, dep_id: uuid.UUID, **fields: str | None) -> None:
        """Record facts (source SHA, image tag, ...) without changing status."""
        _check_fields(fields)
        with self._sessions.begin() as s:
            dep, _ = _lock_pair(s, dep_id)
            for key, value in fields.items():
                setattr(dep, key, value)
            dep.updated_at = _now()

    def transition(self, dep_id: uuid.UUID, new: DeploymentStatus, **fields: str | None) -> None:
        """Move a deployment along the state machine and mirror it onto the app."""
        _check_fields(fields)
        with self._sessions.begin() as s:
            dep, app = _lock_pair(s, dep_id)
            current = DeploymentStatus(dep.status)
            path = GoldenPath(app.golden_path)
            if not transition_allowed(path, current, new):
                raise InvalidTransition(f"{path.value}: {current.value} -> {new.value} is not allowed")
            _apply(s, dep, app, new, fields)

    def fail(self, dep_id: uuid.UUID, code: ErrorCode, message: str) -> None:
        """Platform-error path: FAILED from any in-progress state (spec section 25)."""
        with self._sessions.begin() as s:
            dep, app = _lock_pair(s, dep_id)
            if DeploymentStatus(dep.status) not in IN_PROGRESS:
                return  # already terminal; never overwrite a RUNNING/FAILED outcome
            _apply(
                s, dep, app, DeploymentStatus.FAILED,
                {"error_code": code.value, "error_message": message},
            )


# ---- helpers (caller owns the transaction) ----


def _dep_record_or_none(row: DeploymentRow | None) -> DeploymentRecord | None:
    return _dep_record(row) if row else None


def _latest_row(s: Session, app_id: uuid.UUID) -> DeploymentRow | None:
    return s.scalars(
        select(DeploymentRow)
        .where(DeploymentRow.application_id == app_id)
        .order_by(DeploymentRow.created_at.desc(), DeploymentRow.id.desc())
        .limit(1)
    ).first()


def _check_fields(fields: dict) -> None:
    bad = set(fields) - _SETTABLE
    if bad:
        raise ValueError(f"cannot set {sorted(bad)}")


def _lock_pair(s: Session, dep_id: uuid.UUID) -> tuple[DeploymentRow, ApplicationRow]:
    dep = s.get(DeploymentRow, dep_id, with_for_update=True)
    if dep is None:
        raise DeploymentNotFound(str(dep_id))
    app = s.get(ApplicationRow, dep.application_id, with_for_update=True)
    return dep, app


def _apply(s: Session, dep: DeploymentRow, app: ApplicationRow, new: DeploymentStatus, fields: dict) -> None:
    now = _now()
    for key, value in fields.items():
        setattr(dep, key, value)
    dep.status = new.value
    dep.updated_at = now
    if new in (DeploymentStatus.RUNNING, DeploymentStatus.FAILED) and dep.completed_at is None:
        dep.completed_at = now
    # The app's status always mirrors its LATEST deployment.
    latest = _latest_row(s, app.id)
    if latest is not None and latest.id == dep.id:
        app.current_status = new.value
        app.updated_at = now
