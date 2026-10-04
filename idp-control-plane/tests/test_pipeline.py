"""Phase 3 pipeline: clone -> record source commit -> validate -> outcome.

Real PostgreSQL, real git (against the fake GitHub), real validators.
Build/deploy (Phases 4-5) do not exist yet, so a repository that passes
validation must still end FAILED / PIPELINE_NOT_IMPLEMENTED, loudly.
"""
import os
import re
import tempfile
from functools import partial

import pytest

from app.models import DeploymentStatus as S, ErrorCode, GoldenPath
from app.pipeline import run_deployment, run_guarded
from conftest import make_client, wait_for

SITE = {"index.html": "<h1>hello</h1>", "styles.css": "body{}"}
API = {
    "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
    "requirements.txt": "fastapi\nuvicorn\n",
}
SHA = re.compile(r"^[0-9a-f]{40}$")


def deploy(store, name, path, repo=None):
    return store.create_deployment(
        name=name, golden_path=path,
        repository_url=repo or f"https://github.com/example/{name}",
        namespace=f"app-{name}", live_url=f"https://{name}.apps.test.example",
    )


def run(store, settings, dep):
    run_deployment(dep.id, store, settings=settings)
    return store.get_deployment(dep.id)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    path = tmp_path / "tmp"
    path.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(path))
    return path


# ------------------------------------------------- repositories that pass


@pytest.mark.parametrize("path, files", [(GoldenPath.STATIC, SITE), (GoldenPath.FASTAPI, API)])
def test_valid_repository_stops_after_validation_loudly(store, settings, remotes, path, files):
    sha = remotes.create("example", "demo-app", files)
    _, dep = deploy(store, "demo-app", path)
    done = run(store, settings, dep)

    assert done.status == S.FAILED and done.error_code == "PIPELINE_NOT_IMPLEMENTED"
    assert "validated successfully" in done.error_message and sha[:7] in done.error_message
    assert done.source_revision == sha
    # Later phases fill these in; Phase 3 must not pretend to have done their work.
    assert done.image_tag is None and done.gitops_commit is None
    assert done.completed_at is not None
    assert store.get_application("demo-app").current_status == S.FAILED


# ------------------------------------------------- repositories that fail


def test_missing_index_html(store, settings, remotes):
    sha = remotes.create("example", "demo-app", {"about.html": "x"})
    _, dep = deploy(store, "demo-app", GoldenPath.STATIC)
    done = run(store, settings, dep)
    assert (done.status, done.error_code) == (S.FAILED, "GOLDEN_PATH_VIOLATION")
    assert "index.html" in done.error_message
    assert done.source_revision == sha  # we still record exactly which commit was rejected


@pytest.mark.parametrize("files, symlinks, code, fragment", [
    ({"index.html": "x", "logo.png": "x"}, None, "GOLDEN_PATH_VIOLATION", "Unsupported file types"),
    ({"index.html": "x", "bad name.txt": "x"}, None, "GOLDEN_PATH_VIOLATION", "Unsafe"),
    ({"index.html": "x"}, {"leak.txt": "/etc/hostname"}, "GOLDEN_PATH_VIOLATION", "Symbolic links"),
    ({"index.html": os.urandom(901 * 1024).hex()[: 901 * 1024]}, None, "STATIC_SITE_TOO_LARGE", "limit is 900 KiB"),
])
def test_static_contract_failures(store, settings, remotes, files, symlinks, code, fragment):
    remotes.create("example", "demo-app", files, symlinks=symlinks)
    _, dep = deploy(store, "demo-app", GoldenPath.STATIC)
    done = run(store, settings, dep)
    assert (done.status, done.error_code) == (S.FAILED, code)
    assert fragment in done.error_message
    assert SHA.match(done.source_revision)


def test_fastapi_contract_failures(store, settings, remotes):
    remotes.create("example", "demo-app", {
        "main.py": "from flask import Flask\napp = Flask(__name__)\n", "requirements.txt": "flask\n",
    })
    _, dep = deploy(store, "demo-app", GoldenPath.FASTAPI)
    done = run(store, settings, dep)
    assert (done.status, done.error_code) == (S.FAILED, "GOLDEN_PATH_VIOLATION")
    assert "never imports fastapi" in done.error_message


def test_the_golden_path_is_the_developers_choice_and_is_enforced(store, settings, remotes):
    remotes.create("example", "a-site", SITE)
    remotes.create("example", "an-api", API)
    _, as_api = deploy(store, "a-site", GoldenPath.FASTAPI)       # static repo deployed as FastAPI
    _, as_site = deploy(store, "an-api", GoldenPath.STATIC)       # FastAPI repo deployed as static
    assert "main.py was not found" in run(store, settings, as_api).error_message
    assert "No index.html" in run(store, settings, as_site).error_message  # the missing entry point comes first


# ------------------------------------------------- clone failures


def test_repository_that_does_not_exist(store, settings):
    _, dep = deploy(store, "ghost-app", GoldenPath.STATIC)
    done = run(store, settings, dep)
    assert (done.status, done.error_code) == (S.FAILED, "CLONE_FAILED")
    assert done.source_revision is None  # nothing was ever cloned


def test_repository_that_is_private_or_missing_on_github(store, settings, remotes):
    remotes.set_mode(fake_stderr="fatal: could not read Username for 'https://github.com': terminal prompts disabled\n")
    _, dep = deploy(store, "demo-app", GoldenPath.STATIC)
    done = run(store, settings, dep)
    assert done.error_code == "INVALID_REPOSITORY" and "not public" in done.error_message


def test_empty_repository(store, settings, remotes):
    remotes.create_empty("example", "demo-app")
    _, dep = deploy(store, "demo-app", GoldenPath.STATIC)
    assert run(store, settings, dep).error_code == "INVALID_REPOSITORY"


def test_clone_limits_come_from_settings(store, settings, remotes):
    remotes.create("example", "demo-app", {"index.html": "x", "blob.txt": os.urandom(3 * 1024 * 1024)})
    _, dep = deploy(store, "demo-app", GoldenPath.STATIC)
    tiny = settings.model_copy(update={"clone_max_mib": 1})
    done = run(store, tiny, dep)
    assert done.error_code == "CLONE_FAILED" and "1 MiB" in done.error_message


# ------------------------------------------------- platform faults + hygiene


def test_a_missing_git_binary_is_an_internal_error_not_the_developers_fault(store, settings):
    broken = settings.model_copy(update={"git_binary": "/nonexistent/git"})
    _, dep = deploy(store, "demo-app", GoldenPath.STATIC)
    with pytest.raises(FileNotFoundError):  # the pipeline itself lets platform faults propagate...
        run_deployment(dep.id, store, settings=broken)
    run_guarded(partial(run_deployment, settings=broken), dep.id, store)  # ...the guard records them
    done = store.get_deployment(dep.id)
    assert (done.status, done.error_code) == (S.FAILED, "INTERNAL_ERROR")
    assert "nonexistent" not in done.error_message  # details stay in the logs


def test_no_temp_directories_survive_any_outcome(store, settings, remotes, scratch):
    remotes.create("example", "good-app", SITE)
    remotes.create("example", "bad-app", {"about.html": "x"})
    for name in ("good-app", "bad-app", "no-such-app"):
        _, dep = deploy(store, name, GoldenPath.STATIC)
        run(store, settings, dep)
    assert list(scratch.glob("idp-clone-*")) == []


def test_pipeline_reads_the_application_through_the_store(store):
    app, dep = deploy(store, "demo-app", GoldenPath.FASTAPI)
    assert store.get_application_by_id(dep.application_id).name == "demo-app"
    assert store.get_application_by_id(app.id).golden_path == GoldenPath.FASTAPI


# ------------------------------------------------- through the real API


def test_api_shows_validating_while_the_clone_runs_then_the_outcome(settings, remotes):
    sha = remotes.create("example", "portfolio", SITE)
    remotes.set_mode(sleep_before=1.5)  # make the clone take a moment so we can look at it
    with make_client(settings) as c:
        body = {"name": "portfolio", "golden_path": "static", "repository": "https://github.com/example/portfolio"}
        assert c.post("/deploy", json=body).status_code == 202
        wait_for(lambda: c.get("/apps/portfolio").json()["status"] == "validating")
        wait_for(lambda: c.get("/apps/portfolio").json()["status"] == "failed", timeout=10)
        latest = c.get("/apps/portfolio").json()["latest_deployment"]
        assert latest["source_revision"] == sha
        assert latest["error_code"] == "PIPELINE_NOT_IMPLEMENTED"
        assert "image_tag" in latest and latest["image_tag"] is None


def test_api_surfaces_the_actionable_message(settings, remotes):
    remotes.create("example", "portfolio", {"public/index.html": "x"})
    with make_client(settings) as c:
        c.post("/deploy", json={"name": "portfolio", "golden_path": "static",
                                "repository": "https://github.com/example/portfolio"})
        wait_for(lambda: c.get("/apps/portfolio").json()["status"] == "failed")
        latest = c.get("/apps/portfolio").json()["latest_deployment"]
        assert latest["error_code"] == "GOLDEN_PATH_VIOLATION"
        assert "'public/index.html'" in latest["error_message"]


def test_fixing_the_repository_and_redeploying_is_a_new_attempt(settings, remotes, store, engine):
    body = {"name": "portfolio", "golden_path": "static", "repository": "https://github.com/example/portfolio"}
    remotes.create("example", "portfolio", {"about.html": "x"})  # broken first version
    with make_client(settings) as c:
        first = c.post("/deploy", json=body).json()["deployment_id"]
        wait_for(lambda: c.get("/apps/portfolio").json()["status"] == "failed")
        assert c.get("/apps/portfolio").json()["latest_deployment"]["error_code"] == "GOLDEN_PATH_VIOLATION"

        # developer fixes the repo; same name is deployed again
        (remotes.root / "remotes" / "example" / "portfolio.git").rename(remotes.root / "old.git")
        fixed_sha = remotes.create("example", "portfolio-fixed", SITE)
        (remotes.root / "remotes" / "example" / "portfolio-fixed.git").rename(
            remotes.root / "remotes" / "example" / "portfolio.git")

        second = c.post("/deploy", json=body).json()["deployment_id"]
        wait_for(lambda: c.get("/apps/portfolio").json()["latest_deployment"]["deployment_id"] == second
                 and c.get("/apps/portfolio").json()["status"] == "failed")
        latest = c.get("/apps/portfolio").json()["latest_deployment"]
        assert latest["error_code"] == "PIPELINE_NOT_IMPLEMENTED" and latest["source_revision"] == fixed_sha
    assert first != second
    with engine.connect() as conn:  # history of both attempts is kept
        rows = conn.exec_driver_sql("SELECT error_code FROM deployments ORDER BY created_at").fetchall()
    assert [r[0] for r in rows] == ["GOLDEN_PATH_VIOLATION", "PIPELINE_NOT_IMPLEMENTED"]
