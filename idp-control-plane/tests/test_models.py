import pytest
from pydantic import TypeAdapter, ValidationError

from app.models import (
    DeployRequest,
    DeploymentStatus,
    GoldenPath,
    transition_allowed,
)

adapter = TypeAdapter(DeployRequest)
REPO = "https://github.com/example/weather-api"


def parse(**over):
    body = {"name": "weather-api", "golden_path": "fastapi", "repository": REPO} | over
    return adapter.validate_python(body)


# ---- application name (spec section 10) ----

@pytest.mark.parametrize("name", ["abc", "weather-api", "a1b", "x" * 30, "a-b", "123", "my-app-2"])
def test_valid_names(name):
    assert parse(name=name).name == name


@pytest.mark.parametrize(
    "name",
    [
        "a",           # spec's regex alone would accept this; 3-30 chars is also required
        "ab",
        "x" * 31,
        "Weather-API",  # never silently lowercased
        "-abc",
        "abc-",
        "my_app",
        "my app",
        "my.app",
        "",
    ],
)
def test_invalid_names(name):
    with pytest.raises(ValidationError):
        parse(name=name)


# ---- golden path (exactly two) ----

def test_discriminated_union_picks_model():
    assert parse(golden_path="static").golden_path == "static"
    assert parse(golden_path="fastapi").golden_path == "fastapi"


@pytest.mark.parametrize("gp", ["node", "flask", "STATIC", "", None])
def test_unsupported_golden_path(gp):
    with pytest.raises(ValidationError):
        parse(golden_path=gp)


# ---- unknown fields are rejected (spec: no env/port/replicas/image/...) ----

@pytest.mark.parametrize(
    "extra",
    [
        {"env": {"LOG_LEVEL": "INFO"}},
        {"port": 8080},
        {"replicas": 3},
        {"image": "nginx:latest"},
        {"namespace": "kube-system"},
        {"hostname": "evil.example.com"},
        {"dockerfile": "FROM scratch"},
        {"branch": "dev"},
    ],
)
def test_extra_fields_forbidden(extra):
    with pytest.raises(ValidationError) as exc:
        parse(**extra)
    assert any(e["type"] == "extra_forbidden" for e in exc.value.errors())


# ---- repository URL ----

@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example/weather-api",
        "https://github.com/example/weather-api/",
        "https://github.com/example/weather-api.git",
        "https://github.com/Example-Org/my.repo_name",
    ],
)
def test_valid_repositories(url):
    assert str(parse(repository=url).repository).startswith("https://github.com/")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/example/weather-api",              # not https
        "https://gitlab.com/example/weather-api",             # not github
        "https://www.github.com/example/weather-api",         # host must be exactly github.com
        "https://github.com.evil.com/example/weather-api",
        "https://github.com@evil.com/example/weather-api",    # userinfo trick
        "https://user:token@github.com/example/weather-api",  # embedded credentials
        "https://github.com:8443/example/weather-api",
        "https://github.com/example/weather-api?ref=dev",
        "https://github.com/example/weather-api#readme",
        "https://github.com/example",                          # owner only
        "https://github.com/example/weather-api/tree/dev",     # branch selection is out of scope
        "https://github.com/",
        "https://github.com/example/..",
        "https://github.com/-bad/repo",
        "git@github.com:example/weather-api.git",
        "ftp://github.com/example/weather-api",
        "not a url",
    ],
)
def test_invalid_repositories(url):
    with pytest.raises(ValidationError):
        parse(repository=url)


# ---- state machine (spec section 13) ----

S, G = DeploymentStatus, GoldenPath


def test_static_happy_path_skips_building():
    path = [S.PENDING, S.VALIDATING, S.DEPLOYING, S.RUNNING]
    assert all(transition_allowed(G.STATIC, a, b) for a, b in zip(path, path[1:]))
    assert not transition_allowed(G.STATIC, S.VALIDATING, S.BUILDING)


def test_fastapi_happy_path_includes_building():
    path = [S.PENDING, S.VALIDATING, S.BUILDING, S.DEPLOYING, S.RUNNING]
    assert all(transition_allowed(G.FASTAPI, a, b) for a, b in zip(path, path[1:]))
    assert not transition_allowed(G.FASTAPI, S.VALIDATING, S.DEPLOYING)


@pytest.mark.parametrize("gp", [G.STATIC, G.FASTAPI])
def test_failures_and_runtime_transitions(gp):
    assert transition_allowed(gp, S.VALIDATING, S.FAILED)
    assert transition_allowed(gp, S.DEPLOYING, S.FAILED)
    assert transition_allowed(gp, S.RUNNING, S.CRASHING)
    assert transition_allowed(gp, S.CRASHING, S.RUNNING)
    assert transition_allowed(gp, S.DEPLOYING, S.CRASHING)  # first-deploy ImagePullBackOff
    assert not transition_allowed(gp, S.FAILED, S.RUNNING)  # FAILED is terminal
    assert not transition_allowed(gp, S.RUNNING, S.DEPLOYING)
    assert not transition_allowed(gp, S.PENDING, S.RUNNING)


def test_building_failure_only_for_fastapi():
    assert transition_allowed(G.FASTAPI, S.BUILDING, S.FAILED)
    assert not transition_allowed(G.STATIC, S.BUILDING, S.FAILED)
