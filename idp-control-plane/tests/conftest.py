"""Test fixtures. Tests run against a REAL PostgreSQL (no SQLite, no mocks).

    docker compose up -d db        # from idp-control-plane/
    pytest

TEST_DATABASE_URL overrides the default below. The database name must end in
`_test`: every test starts by TRUNCATE-ing the tables, and we refuse to do
that to anything that doesn't look like a throwaway database.
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.config import Settings, normalize_database_url
from app.db import create_schema, make_engine
from app.main import create_app
from app.models import DeploymentStatus, ErrorCode
from app.store import Store

TEST_DATABASE_URL = normalize_database_url(
    os.environ.get("TEST_DATABASE_URL", "postgresql://idp:idp@localhost:5432/idp_test")
)

GOOD = {"name": "weather-api", "golden_path": "fastapi", "repository": "https://github.com/example/weather-api"}
STATIC = {"name": "portfolio", "golden_path": "static", "repository": "https://github.com/example/portfolio"}

_created_apps: list = []


# ---------------------------------------------------------------- database


def _ensure_database_exists(url) -> None:
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database})
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def engine():
    url = make_url(TEST_DATABASE_URL)
    if not (url.database or "").endswith("_test"):
        pytest.exit(
            f"Refusing to run: test database '{url.database}' must end in '_test' "
            "(tests TRUNCATE all tables).", returncode=2,
        )
    try:
        _ensure_database_exists(url)
        eng = make_engine(TEST_DATABASE_URL)
        create_schema(eng)
    except OperationalError as exc:
        pytest.exit(
            "PostgreSQL is not reachable for tests. Start it with `docker compose up -d db` "
            f"(or set TEST_DATABASE_URL).\n{str(exc.orig).strip()}", returncode=2,
        )
    yield eng
    eng.dispose()


@pytest.fixture
def clean_db(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE deployments, applications"))


@pytest.fixture
def settings(clean_db) -> Settings:
    yield Settings(platform_domain="apps.test.example", job_workers=1, database_url=TEST_DATABASE_URL)
    # Let any pipeline thread still running finish before the NEXT test
    # truncates the tables underneath it.
    for app in _created_apps:
        app.state.runner.shutdown(wait=True)
    _created_apps.clear()


@pytest.fixture
def store(clean_db, engine) -> Store:
    return Store(engine)


# ---------------------------------------------------------------- pipelines


class GatedPipeline:
    """Test pipeline that parks in VALIDATING until the test releases it."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls: list = []

    def __call__(self, dep_id, store: Store) -> None:
        self.calls.append(dep_id)
        store.transition(dep_id, DeploymentStatus.VALIDATING)
        self.started.set()
        assert self.release.wait(10), "test never released the pipeline"
        store.fail(dep_id, ErrorCode.GOLDEN_PATH_VIOLATION, "gated pipeline finished")


class SpyPipeline:
    """Records calls and does nothing, so state stays `pending`."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, dep_id, store: Store) -> None:
        self.calls.append(dep_id)


@pytest.fixture
def gated() -> GatedPipeline:
    return GatedPipeline()


@pytest.fixture
def spy() -> SpyPipeline:
    return SpyPipeline()


# ---------------------------------------------------------------- helpers


def make_client(settings, pipeline=None):
    kwargs = {"pipeline": pipeline} if pipeline is not None else {}
    app = create_app(settings=settings, **kwargs)
    _created_apps.append(app)
    return TestClient(app)


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")
