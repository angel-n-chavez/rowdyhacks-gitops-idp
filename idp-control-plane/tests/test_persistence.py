"""Phase 2: what PostgreSQL adds. Schema fidelity to spec section 14, survival
across restarts, safety under concurrency, and database-enforced integrity."""
import threading
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.models import DeploymentStatus as S, ErrorCode, GoldenPath
from app.store import GoldenPathConflict, Store
from conftest import GOOD, STATIC, TEST_DATABASE_URL, make_client, wait_for


def new(store, name="demo-app", gp=GoldenPath.STATIC, repo="https://github.com/o/r"):
    return store.create_deployment(
        name=name, golden_path=gp, repository_url=repo,
        namespace=f"app-{name}", live_url=f"https://{name}.example.com",
    )


def scalar(engine, sql, **params):
    with engine.connect() as c:
        return c.scalar(text(sql), params)


# ------------------------------------------------------- schema = spec 14

# (type, nullable) exactly as written in the spec's "required logical columns".
SPEC_APPLICATIONS = {
    "id": ("UUID", False), "name": ("VARCHAR", False), "golden_path": ("VARCHAR", False),
    "repository_url": ("TEXT", False), "namespace": ("VARCHAR", False), "live_url": ("TEXT", False),
    "current_status": ("VARCHAR", False), "created_at": ("TIMESTAMPTZ", False),
    "updated_at": ("TIMESTAMPTZ", False),
}
SPEC_DEPLOYMENTS = {
    "id": ("UUID", False), "application_id": ("UUID", False), "status": ("VARCHAR", False),
    "source_revision": ("VARCHAR", True), "image_tag": ("TEXT", True), "gitops_commit": ("VARCHAR", True),
    "error_code": ("VARCHAR", True), "error_message": ("TEXT", True),
    "created_at": ("TIMESTAMPTZ", False), "updated_at": ("TIMESTAMPTZ", False),
    "completed_at": ("TIMESTAMPTZ", True),
}


def _kind(col) -> str:
    t = col["type"]
    name = type(t).__name__
    return "TIMESTAMPTZ" if name == "TIMESTAMP" and t.timezone else name


@pytest.mark.parametrize(
    "table,spec", [("applications", SPEC_APPLICATIONS), ("deployments", SPEC_DEPLOYMENTS)]
)
def test_columns_match_the_spec_exactly(engine, table, spec):
    actual = {c["name"]: (_kind(c), c["nullable"]) for c in inspect(engine).get_columns(table)}
    # Equality, not subset: no stray columns either (no `env`, no `started_at`).
    assert actual == spec


def test_keys_and_constraints(engine):
    insp = inspect(engine)
    assert insp.get_pk_constraint("applications")["constrained_columns"] == ["id"]
    assert insp.get_pk_constraint("deployments")["constrained_columns"] == ["id"]
    assert ["name"] in [u["column_names"] for u in insp.get_unique_constraints("applications")]
    (fk,) = insp.get_foreign_keys("deployments")
    assert (fk["constrained_columns"], fk["referred_table"], fk["referred_columns"]) == (
        ["application_id"], "applications", ["id"],
    )


# ------------------------------------------------------- database integrity

def test_database_rejects_duplicate_names_and_orphan_deployments(store, engine):
    new(store)
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO applications VALUES (:i,'demo-app','static','u','n','l','pending',now(),now())"
            ), {"i": uuid.uuid4()})
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text(
                "INSERT INTO deployments (id, application_id, status, created_at, updated_at) "
                "VALUES (:i, :a, 'pending', now(), now())"
            ), {"i": uuid.uuid4(), "a": uuid.uuid4()})  # no such application


def test_deleting_an_application_removes_its_attempts(store, engine):
    new(store); new(store)
    assert scalar(engine, "SELECT count(*) FROM deployments") == 2
    with engine.begin() as c:
        c.execute(text("DELETE FROM applications WHERE name = 'demo-app'"))
    assert scalar(engine, "SELECT count(*) FROM deployments") == 0


# ------------------------------------------------------- three separate facts

def test_source_image_and_gitops_values_are_separate_columns(store, engine):
    _, d = new(store, name="weather-api", gp=GoldenPath.FASTAPI)
    store.update_fields(d.id, source_revision="a81f32c")
    store.update_fields(d.id, image_tag="reg.example.com/rowdyhacks/weather-api:a81f32c")
    store.update_fields(d.id, gitops_commit="9fd31ab")
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT source_revision, image_tag, gitops_commit FROM deployments WHERE id = :i"), {"i": d.id}
        ).one()
    assert tuple(row) == ("a81f32c", "reg.example.com/rowdyhacks/weather-api:a81f32c", "9fd31ab")


def test_static_deployment_never_gets_an_image_tag(store, engine):
    _, d = new(store, name="portfolio", gp=GoldenPath.STATIC)
    store.transition(d.id, S.VALIDATING, source_revision="b7c2d1e")
    store.transition(d.id, S.DEPLOYING, gitops_commit="1a2b3c4")
    store.transition(d.id, S.RUNNING)
    assert scalar(engine, "SELECT image_tag FROM deployments WHERE id = :i", i=d.id) is None
    got = store.get_deployment(d.id)
    assert (got.source_revision, got.image_tag, got.gitops_commit) == ("b7c2d1e", None, "1a2b3c4")


def test_error_fields_are_persisted(store):
    _, d = new(store)
    store.transition(d.id, S.VALIDATING)
    store.transition(d.id, S.FAILED, error_code=ErrorCode.GOLDEN_PATH_VIOLATION.value,
                     error_message="Missing index.html at the repository root.")
    got = store.get_deployment(d.id)
    assert got.status == S.FAILED and got.completed_at is not None
    assert got.error_code == "GOLDEN_PATH_VIOLATION" and "index.html" in got.error_message


# ------------------------------------------------------- latest + redeploy

def test_latest_deployment_is_the_newest_attempt_and_history_is_kept(store, engine):
    app, d1 = new(store)
    _, d2 = new(store)
    _, d3 = new(store)
    assert store.get_latest_deployment(app.id).id == d3.id
    assert scalar(engine, "SELECT count(*) FROM deployments") == 3
    assert scalar(engine, "SELECT count(*) FROM applications") == 1
    # An old attempt finishing must not rewrite the app's status.
    store.transition(d1.id, S.VALIDATING)
    assert store.get_application("demo-app").current_status == S.PENDING
    store.transition(d3.id, S.VALIDATING)
    assert store.get_application("demo-app").current_status == S.VALIDATING


def test_redeploy_through_the_api_adds_a_row_not_an_app(settings, spy, engine):
    with make_client(settings, spy) as c:
        c.post("/deploy", json=GOOD)
        c.post("/deploy", json=GOOD)
        assert len(c.get("/apps").json()) == 1
    assert scalar(engine, "SELECT count(*) FROM applications") == 1
    assert scalar(engine, "SELECT count(*) FROM deployments") == 2


# ------------------------------------------------------- survives restarts

def test_data_survives_a_brand_new_connection_pool(store):
    _, d = new(store)
    store.transition(d.id, S.VALIDATING, source_revision="a81f32c")
    reopened = Store(make_engine(TEST_DATABASE_URL))  # what a restarted process has
    try:
        got = reopened.get_deployment(d.id)
        assert (got.status, got.source_revision) == (S.VALIDATING, "a81f32c")
        assert reopened.get_application("demo-app").current_status == S.VALIDATING
    finally:
        reopened.dispose()


def test_restart_fails_inflight_work_but_keeps_running_apps(settings, gated, store):
    _, live = new(store, name="live-site")
    for step in (S.VALIDATING, S.DEPLOYING, S.RUNNING):
        store.transition(live.id, step)

    with make_client(settings, gated) as before:
        before.post("/deploy", json=GOOD)
        assert gated.started.wait(5)
        assert before.get("/apps/weather-api").json()["status"] == "validating"
    # `before` is now shut down, but its worker is still parked mid-deployment.
    # A new app instance on the same database is exactly "the process restarted".
    with make_client(settings) as after:
        lost = after.get("/apps/weather-api").json()
        assert lost["status"] == "failed"
        assert lost["latest_deployment"]["error_code"] == "INTERNAL_ERROR"
        assert "restarted" in lost["latest_deployment"]["error_message"]
        assert lost["latest_deployment"]["completed_at"] is not None
        assert after.get("/apps/live-site").json()["status"] == "running"  # untouched

    gated.release.set()  # the old worker wakes up and tries to report its own failure...
    before.app.state.runner.shutdown(wait=True)
    latest = store.get_latest_deployment(store.get_application("weather-api").id)
    assert latest.error_code == "INTERNAL_ERROR"  # ...and must not overwrite the restart outcome


def test_fail_orphaned_only_touches_in_progress_deployments(store):
    states = {}
    for name, path in [("p-pending", GoldenPath.STATIC), ("p-valid", GoldenPath.STATIC),
                       ("p-build", GoldenPath.FASTAPI), ("p-deploy", GoldenPath.STATIC),
                       ("p-run", GoldenPath.STATIC), ("p-crash", GoldenPath.STATIC),
                       ("p-failed", GoldenPath.STATIC)]:
        _, d = new(store, name=name, gp=path)
        states[name] = d.id
    store.transition(states["p-valid"], S.VALIDATING)
    store.transition(states["p-build"], S.VALIDATING); store.transition(states["p-build"], S.BUILDING)
    for n in ("p-deploy", "p-run", "p-crash"):
        store.transition(states[n], S.VALIDATING); store.transition(states[n], S.DEPLOYING)
    for n in ("p-run", "p-crash"):
        store.transition(states[n], S.RUNNING)
    store.transition(states["p-crash"], S.CRASHING)
    store.transition(states["p-failed"], S.VALIDATING)
    store.transition(states["p-failed"], S.FAILED, error_code="CLONE_FAILED", error_message="x")

    assert store.fail_orphaned() == 4  # pending, validating, building, deploying
    got = {n: store.get_deployment(i).status for n, i in states.items()}
    assert got == {"p-pending": S.FAILED, "p-valid": S.FAILED, "p-build": S.FAILED, "p-deploy": S.FAILED,
                   "p-run": S.RUNNING, "p-crash": S.CRASHING, "p-failed": S.FAILED}
    assert store.get_deployment(states["p-failed"]).error_code == "CLONE_FAILED"  # not overwritten
    assert store.fail_orphaned() == 0  # idempotent


def test_schema_creation_is_idempotent(store):
    new(store)
    store.create_schema()
    store.create_schema()
    assert store.get_application("demo-app") is not None  # data untouched


def test_app_refuses_to_start_without_a_database(clean_db):
    bad = Settings(platform_domain="apps.test.example",
                   database_url="postgresql://idp:idp@127.0.0.1:1/idp")  # nothing listens on :1
    with pytest.raises(OperationalError):
        with TestClient(create_app(settings=bad)):
            pass


# ------------------------------------------------------- concurrency

def _race(n, fn):
    barrier, results, errors = threading.Barrier(n), [], []

    def run(i):
        barrier.wait()  # release all threads at once
        try:
            results.append(fn(i))
        except Exception as exc:  # noqa: BLE001 - we want to see every kind
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    return results, errors


def test_simultaneous_first_deploys_of_one_name_make_one_app(store, engine):
    results, errors = _race(16, lambda i: new(store, name="race-app"))
    assert errors == []  # no unique-violation leaking out as a 500
    assert len({app.id for app, _ in results}) == 1
    assert len({dep.id for _, dep in results}) == 16
    assert scalar(engine, "SELECT count(*) FROM applications") == 1
    assert scalar(engine, "SELECT count(*) FROM deployments") == 16
    latest = store.get_latest_deployment(results[0][0].id)
    assert latest.id in {dep.id for _, dep in results}


def test_golden_path_race_has_exactly_one_winner(store, engine):
    paths = [GoldenPath.STATIC, GoldenPath.FASTAPI]
    results, errors = _race(10, lambda i: new(store, name="path-race", gp=paths[i % 2]))
    assert all(isinstance(e, GoldenPathConflict) for e in errors)  # losers get the 409 error, nothing else
    assert len(results) + len(errors) == 10 and results
    winner = {app.golden_path for app, _ in results}
    assert len(winner) == 1 and store.get_application("path-race").golden_path in winner
    assert scalar(engine, "SELECT count(*) FROM deployments") == len(results)  # losers left no rows


def test_simultaneous_api_deploys_are_all_accepted(settings, spy):
    with make_client(settings, spy) as c:
        results, errors = _race(12, lambda i: c.post("/deploy", json=GOOD).status_code)
        assert errors == [] and results == [202] * 12
        assert len(c.get("/apps").json()) == 1
    assert len(spy.calls) == 12


# ------------------------------------------------------- timestamps

def test_timestamps_are_utc_even_if_the_database_session_is_not(clean_db):
    chicago = create_engine(TEST_DATABASE_URL, connect_args={"options": "-c timezone=America/Chicago"})
    st = Store(chicago)
    try:
        _, d = new(st)
        with chicago.connect() as c:  # prove the premise: raw values really do come back non-UTC
            raw = c.scalar(text("SELECT created_at FROM deployments WHERE id = :i"), {"i": d.id})
        assert raw.utcoffset() != timedelta(0)
        got = st.get_deployment(d.id)
        assert got.created_at.utcoffset() == timedelta(0)
        assert got.created_at == raw  # same instant, just normalized
    finally:
        chicago.dispose()


# ------------------------------------------------------- DATABASE_URL

def test_database_url_spellings_are_normalized_and_the_secret_is_hidden():
    s = Settings(platform_domain="x.example", database_url="postgresql://idp:TOPSECRET@localhost/idp")
    assert s.database_url.get_secret_value() == "postgresql+psycopg://idp:TOPSECRET@localhost/idp"
    assert "TOPSECRET" not in repr(s) and "TOPSECRET" not in str(s)


@pytest.mark.parametrize("url", ["sqlite:///idp.db", "mysql://u:LEAKME@h/db", "", "not-a-url"])
def test_non_postgres_urls_are_rejected_without_echoing_them(url):
    with pytest.raises(Exception) as exc:
        Settings(platform_domain="x.example", database_url=url)
    assert "LEAKME" not in str(exc.value)
