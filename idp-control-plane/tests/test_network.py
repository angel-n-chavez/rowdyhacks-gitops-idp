"""Opt-in checks against the REAL github.com:   pytest -m network

Excluded from the default run so the everyday suite stays offline and
deterministic. These prove the production clone path (real git, real GitHub,
no wrapper) behaves as the offline tests assume.
"""
import re
import time
from pathlib import Path

import pytest

from app.clone import cloned_source
from app.golden_path import validate_static
from app.models import DeploymentStatus as S, ErrorCode, GoldenPath, PipelineError
from app.pipeline import run_deployment

pytestmark = pytest.mark.network

SPOON_KNIFE = "https://github.com/octocat/Spoon-Knife"  # index.html + styles.css + README.md
HELLO_WORLD = "https://github.com/octocat/Hello-World"  # README only


def test_real_static_repository_clones_and_validates():
    with cloned_source(SPOON_KNIFE) as src:
        assert re.fullmatch(r"[0-9a-f]{40}", src.sha)
        assert not (src.path / ".git").exists()
        site = validate_static(src.path)
        assert [f.path for f in site.files] == ["index.html", "styles.css"]  # README.md is ignored
    assert not Path(src.path).exists()


def test_real_repository_without_index_html_is_a_violation():
    with cloned_source(HELLO_WORLD) as src:
        with pytest.raises(PipelineError) as exc:
            validate_static(src.path)
    assert exc.value.code == ErrorCode.GOLDEN_PATH_VIOLATION


def test_real_missing_repository_fails_fast_instead_of_prompting_for_a_password():
    started = time.monotonic()
    with pytest.raises(PipelineError) as exc:
        with cloned_source("https://github.com/idp-test-nobody/does-not-exist-9f3a1"):
            pass
    assert time.monotonic() - started < 20
    assert exc.value.code == ErrorCode.INVALID_REPOSITORY
    assert "not public" in exc.value.message


def test_real_repository_through_the_whole_pipeline(store, settings):
    real = settings.model_copy(update={"git_binary": "git"})  # no wrapper: the real thing
    _, dep = store.create_deployment(
        name="spoon-knife", golden_path=GoldenPath.STATIC, repository_url=SPOON_KNIFE,
        namespace="app-spoon-knife", live_url="https://spoon-knife.apps.test.example",
    )
    run_deployment(dep.id, store, settings=real)
    done = store.get_deployment(dep.id)
    assert (done.status, done.error_code) == (S.FAILED, "PIPELINE_NOT_IMPLEMENTED")
    assert re.fullmatch(r"[0-9a-f]{40}", done.source_revision)
