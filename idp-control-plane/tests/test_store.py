import pytest

from app.models import DeploymentStatus as S, ErrorCode, GoldenPath
from app.store import GoldenPathConflict, InvalidTransition


def new(store, name="demo-app", gp=GoldenPath.STATIC, repo="https://github.com/o/r"):
    return store.create_deployment(
        name=name, golden_path=gp, repository_url=repo,
        namespace=f"app-{name}", live_url=f"https://{name}.example.com",
    )


def test_create_makes_app_and_pending_deployment(store):
    app, dep = new(store)
    assert app.current_status == S.PENDING and dep.status == S.PENDING
    assert store.get_application("demo-app").namespace == "app-demo-app"


def test_redeploy_creates_new_attempt_for_same_app(store):
    app1, dep1 = new(store)
    app2, dep2 = new(store, repo="https://github.com/o/other")
    assert app1.id == app2.id and dep1.id != dep2.id
    assert len(store.list_applications()) == 1
    assert store.get_application("demo-app").repository_url == "https://github.com/o/other"
    assert store.get_latest_deployment(app1.id).id == dep2.id


def test_different_golden_path_is_a_conflict(store):
    new(store, gp=GoldenPath.STATIC)
    with pytest.raises(GoldenPathConflict):
        new(store, gp=GoldenPath.FASTAPI)


def test_transitions_mirror_to_app_and_set_completed_at(store):
    app, dep = new(store)
    store.transition(dep.id, S.VALIDATING, source_revision="a81f32c")
    assert store.get_application("demo-app").current_status == S.VALIDATING
    assert store.get_deployment(dep.id).completed_at is None
    store.transition(dep.id, S.DEPLOYING, gitops_commit="deadbee")
    store.transition(dep.id, S.RUNNING)
    done = store.get_deployment(dep.id)
    assert done.completed_at is not None
    assert (done.source_revision, done.gitops_commit, done.image_tag) == ("a81f32c", "deadbee", None)


def test_illegal_transition_is_rejected(store):
    _, dep = new(store)
    with pytest.raises(InvalidTransition):
        store.transition(dep.id, S.RUNNING)  # PENDING -> RUNNING
    assert store.get_deployment(dep.id).status == S.PENDING


def test_static_cannot_enter_building(store):
    _, dep = new(store, gp=GoldenPath.STATIC)
    store.transition(dep.id, S.VALIDATING)
    with pytest.raises(InvalidTransition):
        store.transition(dep.id, S.BUILDING)


def test_old_deployment_does_not_overwrite_app_status(store):
    app, old = new(store)
    _, newer = new(store)
    store.transition(old.id, S.VALIDATING)  # stale attempt still moving
    assert store.get_application("demo-app").current_status == S.PENDING  # tracks the LATEST
    store.transition(newer.id, S.VALIDATING)
    assert store.get_application("demo-app").current_status == S.VALIDATING


def test_fail_from_any_in_progress_state_but_never_overwrites_terminal(store):
    _, dep = new(store)
    store.fail(dep.id, ErrorCode.INTERNAL_ERROR, "boom")  # straight from PENDING
    failed = store.get_deployment(dep.id)
    assert failed.status == S.FAILED and failed.error_code == "INTERNAL_ERROR" and failed.completed_at

    _, dep2 = new(store, name="other-app")
    store.transition(dep2.id, S.VALIDATING)
    store.transition(dep2.id, S.DEPLOYING)
    store.transition(dep2.id, S.RUNNING)
    store.fail(dep2.id, ErrorCode.INTERNAL_ERROR, "late error")
    assert store.get_deployment(dep2.id).status == S.RUNNING


def test_unknown_field_is_refused(store):
    _, dep = new(store)
    with pytest.raises(ValueError):
        store.update_fields(dep.id, env="SECRET=1")
