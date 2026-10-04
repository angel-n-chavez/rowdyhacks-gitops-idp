import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import DeploymentStatus, ErrorCode
from app.store import Store

GOOD = {"name": "weather-api", "golden_path": "fastapi", "repository": "https://github.com/example/weather-api"}
STATIC = {"name": "portfolio", "golden_path": "static", "repository": "https://github.com/example/portfolio"}


@pytest.fixture
def settings() -> Settings:
    return Settings(platform_domain="apps.test.example", job_workers=1)


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


def make_client(settings, pipeline=None):
    kwargs = {"pipeline": pipeline} if pipeline is not None else {}
    return TestClient(create_app(settings=settings, **kwargs))


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")
