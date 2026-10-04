"""SQLAlchemy 2.x tables (spec section 14).

Two tables, exactly the columns the spec lists:

    applications   one row per app name
    deployments    one row per deploy attempt (a redeploy adds a row)

Three different Git/registry facts are kept in three separate columns on
purpose; they are not interchangeable:

    source_revision  the developer's source commit (what the code was)
    image_tag        the container image built from it (NULL for static apps)
    gitops_commit    the commit in the GitOps repo holding the desired state

The schema is created with `create_all` at startup (spec: Alembic MAY be used
but must not block the MVP). Caveat: `create_all` only creates missing tables;
it never alters existing ones. If a column is added later, an existing
database needs a manual ALTER TABLE (or to be dropped and recreated).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _timestamptz() -> DateTime:
    return DateTime(timezone=True)


class ApplicationRow(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    golden_path: Mapped[str] = mapped_column(String)
    repository_url: Mapped[str] = mapped_column(Text)
    namespace: Mapped[str] = mapped_column(String)
    live_url: Mapped[str] = mapped_column(Text)
    current_status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(_timestamptz())
    updated_at: Mapped[datetime] = mapped_column(_timestamptz())


class DeploymentRow(Base):
    __tablename__ = "deployments"
    # "Latest deployment of this app" is the hot query: newest created_at first.
    __table_args__ = (Index("ix_deployments_app_created", "application_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # CASCADE: deleting an application removes its attempts with it. Spec 29
    # leaves "update/remove the application record" to Phase 6; deployment
    # history UI is an explicit non-goal, so nothing needs the orphans.
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String)
    source_revision: Mapped[str | None] = mapped_column(String)
    image_tag: Mapped[str | None] = mapped_column(Text)
    gitops_commit: Mapped[str | None] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_timestamptz())
    updated_at: Mapped[datetime] = mapped_column(_timestamptz())
    completed_at: Mapped[datetime | None] = mapped_column(_timestamptz())


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping: transparently replace connections that went away
    # (database restart, idle timeout) instead of failing the next request.
    return create_engine(database_url, pool_pre_ping=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
