"""Test fixtures. Tests run against a REAL PostgreSQL (no SQLite, no mocks).

    docker compose up -d db        # from idp-control-plane/
    pytest

TEST_DATABASE_URL overrides the default below. The database name must end in
`_test`: every test starts by TRUNCATE-ing the tables, and we refuse to do
that to anything that doesn't look like a throwaway database.
"""
import json
import os
import shutil
import subprocess
import sys
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
def settings(clean_db, remotes) -> Settings:
    # git_binary = the wrapper: every github.com URL is redirected to a local
    # fixture repository, so no test can ever reach the real network by accident.
    yield Settings(
        platform_domain="apps.test.example", job_workers=1, database_url=TEST_DATABASE_URL,
        git_binary=str(remotes.wrapper),
    )
    # Let any pipeline thread still running finish before the NEXT test
    # truncates the tables underneath it.
    for app in _created_apps:
        app.state.runner.shutdown(wait=True)
    _created_apps.clear()


@pytest.fixture
def store(clean_db, engine) -> Store:
    return Store(engine)


# ---------------------------------------------------------------- fake GitHub
#
# `git` is replaced by a wrapper script. It forwards to the REAL git, but
# rewrites https://github.com/<owner>/<repo>[.git] to a local bare repository,
# so tests run the production clone code (same flags, same environment
# hardening) without network access. Tests change its behaviour per test by
# writing a small JSON control file (see Remotes.set_mode).

_WRAPPER = """#!__PYTHON__
import json, os, re, subprocess, sys, time
ROOT, CTL, REAL_GIT = __ROOT__, __CTL__, __GIT__
ctl = json.load(open(CTL)) if os.path.exists(CTL) else {}
args = sys.argv[1:]
if ctl.get("log"):
    with open(ctl["log"], "a") as f:
        f.write(json.dumps({"argv": args, "env": dict(os.environ)}) + "\\n")
is_clone = "clone" in args
if is_clone:
    if ctl.get("pidfile"):
        open(ctl["pidfile"], "w").write(str(os.getpid()))
    if ctl.get("fake_stderr"):
        sys.stderr.write(ctl["fake_stderr"])
        sys.exit(ctl.get("fake_exit", 128))
    time.sleep(ctl.get("sleep_before", 0))
    if ctl.get("spawn_sleep"):
        child = subprocess.Popen(["sleep", "60"])
        open(ctl["spawn_sleep"], "w").write(str(child.pid))
        child.wait()
    rewritten = []
    for a in args:
        m = re.match(r"^https://github\\.com/([^/]+)/([^/]+?)(\\.git)?$", a)
        rewritten.append("file://%s/%s/%s.git" % (ROOT, m.group(1), m.group(2)) if m else a)
    args = ["-c", "protocol.file.allow=always"] + rewritten
rc = subprocess.run([REAL_GIT] + args).returncode
if is_clone:
    time.sleep(ctl.get("sleep_after", 0))
sys.exit(rc)
"""

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(*args, cwd=None):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV},
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


class Remotes:
    """A pretend github.com backed by local bare repositories."""

    def __init__(self, root) -> None:
        self.root = root
        (root / "remotes").mkdir()
        self.ctl = root / "ctl.json"
        self.wrapper = root / "git-wrapper"
        self.wrapper.write_text(
            _WRAPPER.replace("__PYTHON__", sys.executable)
            .replace("__ROOT__", repr(str(root / "remotes")))
            .replace("__CTL__", repr(str(self.ctl)))
            .replace("__GIT__", repr(shutil.which("git")))
        )
        self.wrapper.chmod(0o755)

    def create(self, owner, repo, files, *, symlinks=None, branch="main", history=1, other_branch=None):
        """Create <owner>/<repo>. `files`: {relative path: str|bytes}. Returns HEAD sha."""
        work = self.root / "work" / f"{owner}-{repo}"
        work.mkdir(parents=True)
        _git("init", "-q", "-b", branch, cwd=work)
        for n in range(history):  # extra commits prove the clone really is depth 1
            for rel, content in files.items():
                target = work / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                data = content if isinstance(content, bytes) else content.encode()
                target.write_bytes(data + (f"\n{n}".encode() if n < history - 1 else b""))
            for rel, destination in (symlinks or {}).items():
                link = work / rel
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.is_symlink():
                    os.symlink(destination, link)
            _git("add", "-A", cwd=work)
            _git("commit", "-q", "-m", f"commit {n}", cwd=work)
        sha = _git("rev-parse", "HEAD", cwd=work)
        if other_branch:  # a non-default branch with different content
            _git("checkout", "-q", "-b", "dev", cwd=work)
            for rel, content in other_branch.items():
                (work / rel).write_text(content)
            _git("add", "-A", cwd=work)
            _git("commit", "-q", "-m", "dev work", cwd=work)
            _git("checkout", "-q", branch, cwd=work)
        bare = self.root / "remotes" / owner / f"{repo}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "-q", "--bare", str(work), str(bare))
        return sha

    def create_empty(self, owner, repo):
        bare = self.root / "remotes" / owner / f"{repo}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git("init", "-q", "--bare", str(bare))

    def set_mode(self, **mode):
        """Change wrapper behaviour: log=, pidfile=, sleep_before=, sleep_after=, spawn_sleep=, fake_stderr=."""
        self.ctl.write_text(json.dumps(mode))

    def calls(self, subcommand="clone"):
        log = json.loads(self.ctl.read_text())["log"]
        rows = [json.loads(line) for line in open(log)]
        return [r for r in rows if subcommand in r["argv"]]


@pytest.fixture
def remotes(tmp_path) -> Remotes:
    root = tmp_path / "fake-github"
    root.mkdir()
    return Remotes(root)


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
