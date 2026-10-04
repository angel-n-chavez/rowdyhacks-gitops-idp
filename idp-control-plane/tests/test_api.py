import re

import pytest

from conftest import GOOD, STATIC, make_client, wait_for

DEP_ID = re.compile(r"^dep_[0-9a-f]{32}$")


def test_health_is_minimal(settings):
    with make_client(settings) as c:
        assert c.get("/health").json() == {"status": "ok"}


def test_local_portal_origins_can_call_the_api(settings):
    with make_client(settings) as c:
        response = c.get("/apps", headers={"Origin": "http://localhost:5173"})
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

        preflight = c.options(
            "/deploy",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

        rejected = c.get("/apps", headers={"Origin": "http://example.com"})
        assert "access-control-allow-origin" not in rejected.headers


def test_deploy_returns_202_without_waiting_for_the_pipeline(settings, gated):
    with make_client(settings, gated) as c:
        r = c.post("/deploy", json=GOOD)  # pipeline is parked; this must still return
        assert r.status_code == 202
        body = r.json()
        assert DEP_ID.match(body["deployment_id"])
        assert body["app_name"] == "weather-api"
        assert body["status"] in ("pending", "validating")
        assert body["message"] == "Deployment accepted"
        gated.release.set()


def test_status_moves_while_polling(settings, gated):
    with make_client(settings, gated) as c:
        c.post("/deploy", json=GOOD)
        assert gated.started.wait(5)
        assert c.get("/apps/weather-api").json()["status"] == "validating"
        gated.release.set()
        wait_for(lambda: c.get("/apps/weather-api").json()["status"] == "failed")


def test_app_detail_shape(settings, gated):
    with make_client(settings, gated) as c:
        dep = c.post("/deploy", json=GOOD).json()
        detail = c.get("/apps/weather-api").json()
        assert detail["name"] == "weather-api"
        assert detail["golden_path"] == "fastapi"
        assert detail["repository"] == "https://github.com/example/weather-api"
        assert detail["namespace"] == "app-weather-api"
        assert detail["live_url"] == "https://weather-api.apps.test.example"
        latest = detail["latest_deployment"]
        assert latest["deployment_id"] == dep["deployment_id"]
        assert latest["image_tag"] is None and latest["completed_at"] is None
        assert "env" not in detail and "env" not in latest
        gated.release.set()


def test_second_deployment_waits_in_pending_behind_the_first(settings, gated):
    other = {"name": "second-app", "golden_path": "static", "repository": "https://github.com/example/second"}
    with make_client(settings, gated) as c:
        c.post("/deploy", json=GOOD)
        assert gated.started.wait(5)           # worker is busy with the first
        c.post("/deploy", json=other)
        assert c.get("/apps/second-app").json()["status"] == "pending"
        gated.release.set()                    # first finishes, worker picks up the second
        wait_for(lambda: c.get("/apps/second-app").json()["status"] == "failed")


def test_scaffold_pipeline_fails_loudly_not_silently(settings, remotes):
    # A repository that PASSES validation still ends FAILED until Phases 4-5
    # implement build/deploy, so the scaffold can't be mistaken for a real deploy.
    sha = remotes.create("example", "portfolio", {"index.html": "<h1>hi</h1>"})
    with make_client(settings) as c:           # real run_deployment
        c.post("/deploy", json=STATIC)
        wait_for(lambda: c.get("/apps/portfolio").json()["status"] == "failed")
        latest = c.get("/apps/portfolio").json()["latest_deployment"]
        assert latest["error_code"] == "PIPELINE_NOT_IMPLEMENTED"
        assert latest["source_revision"] == sha
        assert latest["completed_at"] is not None


def test_pipeline_crash_becomes_failed_with_generic_message(settings):
    def exploding(dep_id, store):
        raise RuntimeError("secret-token-abc123 leaked in a traceback")

    with make_client(settings, exploding) as c:
        c.post("/deploy", json=GOOD)
        wait_for(lambda: c.get("/apps/weather-api").json()["status"] == "failed")
        latest = c.get("/apps/weather-api").json()["latest_deployment"]
        assert latest["error_code"] == "INTERNAL_ERROR"
        assert "secret-token" not in latest["error_message"]


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "name": "Weather_API"},
        {**GOOD, "golden_path": "node"},
        {**GOOD, "repository": "https://gitlab.com/example/weather-api"},
        {**GOOD, "repository": "https://user:pw@github.com/example/weather-api"},
        {**GOOD, "env": {"API_KEY": "x"}},
        {**GOOD, "replicas": 5},
        {"name": "weather-api", "golden_path": "fastapi"},  # missing repository
        {},
    ],
)
def test_invalid_requests_get_422_and_start_nothing(settings, spy, bad):
    with make_client(settings, spy) as c:
        assert c.post("/deploy", json=bad).status_code == 422
        assert c.get("/apps").json() == []     # no record created
    assert spy.calls == []                      # no job started


def test_redeploy_creates_new_attempt_not_new_app(settings, spy):
    with make_client(settings, spy) as c:
        first = c.post("/deploy", json=GOOD).json()
        second = c.post("/deploy", json={**GOOD, "repository": "https://github.com/example/weather-api-v2"}).json()
        assert first["deployment_id"] != second["deployment_id"]
        apps = c.get("/apps").json()
        assert len(apps) == 1 and apps[0]["repository"].endswith("weather-api-v2")
        assert c.get("/apps/weather-api").json()["latest_deployment"]["deployment_id"] == second["deployment_id"]


def test_changing_golden_path_is_409_and_starts_nothing(settings, spy):
    with make_client(settings, spy) as c:
        c.post("/deploy", json=GOOD)
        r = c.post("/deploy", json={**GOOD, "golden_path": "static"})
        assert r.status_code == 409
        assert r.json()["error_code"] == "GOLDEN_PATH_CONFLICT"
    assert len(spy.calls) == 1


def test_unknown_app_is_404_with_error_code(settings):
    with make_client(settings) as c:
        r = c.get("/apps/nope")
        assert r.status_code == 404
        assert r.json()["error_code"] == "APP_NOT_FOUND"


def test_list_apps_returns_summaries_only(settings, spy):
    with make_client(settings, spy) as c:
        c.post("/deploy", json=GOOD)
        c.post("/deploy", json=STATIC)
        apps = c.get("/apps").json()
        assert {a["name"] for a in apps} == {"weather-api", "portfolio"}
        assert set(apps[0]) == {"name", "golden_path", "repository", "status", "live_url", "updated_at"}


def test_422_never_echoes_submitted_secrets(settings, spy):
    leaky = {
        **GOOD,
        "repository": "https://octocat:ghp_SUPERSECRET@github.com/example/weather-api",
        "env": {"API_KEY": "hunter2-SECRET"},
    }
    with make_client(settings, spy) as c:
        r = c.post("/deploy", json=leaky)
    assert r.status_code == 422
    assert "SECRET" not in r.text and "hunter2" not in r.text and "ghp_" not in r.text
    assert all({"type", "loc", "msg"} == set(e) for e in r.json()["detail"])
    assert spy.calls == []
