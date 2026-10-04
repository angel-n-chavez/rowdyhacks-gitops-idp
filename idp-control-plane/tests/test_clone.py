"""Phase 3: safe clone. Real git, fake GitHub (see conftest.Remotes): offline."""
import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

from app.clone import _classify_failure, cloned_source
from app.models import ErrorCode, PipelineError

REPO = "https://github.com/example/portfolio"
SITE = {"index.html": "<h1>hello</h1>", "styles.css": "body{}"}


def clone(remotes, url=REPO, **kwargs):
    return cloned_source(url, git_binary=str(remotes.wrapper), **kwargs)


def fails(remotes, url=REPO, code=None, **kwargs) -> PipelineError:
    with pytest.raises(PipelineError) as exc:
        with clone(remotes, url, **kwargs):
            pytest.fail("clone should have failed")
    if code:
        assert exc.value.code == code, exc.value.message
    return exc.value


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """Point tempfile at a directory we can inspect for leftovers."""
    path = tmp_path / "tmp"
    path.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(path))
    return path


def leftovers(scratch):
    return sorted(p.name for p in scratch.glob("idp-clone-*"))


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"  # a zombie is dead, just not reaped yet


# ------------------------------------------------------------------ success


def test_clones_the_default_branch_and_reports_its_sha(remotes):
    sha = remotes.create(
        "example", "portfolio", SITE, branch="trunk", history=3,
        other_branch={"dev-only.txt": "work in progress"},
    )
    with clone(remotes) as src:
        assert src.sha == sha and len(src.sha) == 40
        assert (src.path / "index.html").read_text() == "<h1>hello</h1>"
        assert not (src.path / "dev-only.txt").exists()  # the other branch is not fetched


def test_dot_git_is_removed_before_validation_sees_the_tree(remotes):
    remotes.create("example", "portfolio", SITE)
    with clone(remotes) as src:
        assert not (src.path / ".git").exists()


@pytest.mark.parametrize("url", [REPO, REPO + "/", REPO + ".git", "  " + REPO + "  "])
def test_equivalent_url_spellings(remotes, url):
    sha = remotes.create("example", "portfolio", SITE)
    with clone(remotes, url) as src:
        assert src.sha == sha


def test_symlinks_survive_the_clone_so_the_validator_can_reject_them(remotes):
    remotes.create("example", "portfolio", SITE, symlinks={"leak.txt": "/etc/hostname"})
    with clone(remotes) as src:
        assert (src.path / "leak.txt").is_symlink()  # clone does not hide them; validation must catch them


def test_parallel_clones_do_not_share_directories(remotes):
    remotes.create("example", "portfolio", SITE)
    paths = []

    def go():
        with clone(remotes) as src:
            paths.append(src.path)
            time.sleep(0.2)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(paths)) == 4


# ----------------------------------------------------- what we ask git to do


def test_git_is_invoked_with_the_hardened_arguments_and_environment(remotes, tmp_path, monkeypatch):
    remotes.create("example", "portfolio", SITE)
    monkeypatch.setenv("DATABASE_URL", "postgresql://idp:LEAKED-DB-PASSWORD@h/db")
    monkeypatch.setenv("GITOPS_TOKEN", "ghp_LEAKED_TOKEN")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "LEAKED-AUTH")
    remotes.set_mode(log=str(tmp_path / "calls.jsonl"))

    with clone(remotes):
        pass

    (call,) = remotes.calls("clone")
    argv, env = call["argv"], call["env"]

    # Protocol and credential lockdown
    assert "protocol.allow=never" in argv and "protocol.https.allow=always" in argv
    assert "credential.helper=" in argv
    # Public clone of the default branch only, as shallow as possible
    for flag in ("--depth", "--single-branch", "--no-tags", "--no-recurse-submodules", "--template="):
        assert flag in argv
    assert argv[argv.index("--depth") + 1] == "1"
    assert "--branch" not in argv and "-b" not in argv
    # The URL is passed after `--` so it can never be parsed as an option
    separator = argv.index("--")
    assert argv[separator + 1] == "https://github.com/example/portfolio.git"

    # Environment: prompts off, no user/system git config, no LFS downloads
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull and env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_LFS_SKIP_SMUDGE"] == "1"
    assert "idp-clone-" in env["HOME"]  # private HOME inside the throwaway directory
    # None of the control plane's secrets are visible to git
    assert "LEAKED" not in " ".join(env.values())
    assert not {"DATABASE_URL", "GITOPS_TOKEN", "BASIC_AUTH_PASSWORD"} & set(env)


# ---------------------------------------------------------------- cleanup


def test_temp_directory_is_removed_after_success(remotes, scratch):
    remotes.create("example", "portfolio", SITE)
    with clone(remotes) as src:
        assert src.path.exists() and len(leftovers(scratch)) == 1
    assert leftovers(scratch) == []


def test_temp_directory_is_removed_when_the_body_raises(remotes, scratch):
    remotes.create("example", "portfolio", SITE)
    with pytest.raises(RuntimeError):
        with clone(remotes):
            raise RuntimeError("validation blew up")
    assert leftovers(scratch) == []


def test_temp_directory_is_removed_after_a_failed_clone(remotes, scratch):
    fails(remotes, REPO)  # nothing exists at that URL
    assert leftovers(scratch) == []


# ----------------------------------------------------------- error mapping


@pytest.mark.parametrize("url", [
    "http://github.com/example/portfolio",
    "https://gitlab.com/example/portfolio",
    "https://www.github.com/example/portfolio",
    "https://github.com/example/portfolio/tree/main",
    "https://github.com/example",
    "https://user:token@github.com/example/portfolio",
    "https://github.com/example/..",
    "git@github.com:example/portfolio.git",
    "file:///etc",
    "-c core.sshCommand=evil",
    "",
])
def test_bad_urls_are_rejected_before_git_is_ever_started(remotes, tmp_path, url):
    remotes.set_mode(log=str(tmp_path / "calls.jsonl"))
    error = fails(remotes, url, code=ErrorCode.INVALID_REPOSITORY)
    assert "public GitHub repository URL" in error.message
    assert not (tmp_path / "calls.jsonl").exists()  # git was never launched


def test_missing_repository_is_a_clone_failure_without_leaking_git_output(remotes, tmp_path):
    error = fails(remotes, code=ErrorCode.CLONE_FAILED)
    assert "Could not clone" in error.message
    assert "fatal" not in error.message.lower() and str(tmp_path) not in error.message


def test_private_or_nonexistent_github_repo_is_invalid_repository(remotes):
    # Exactly what real GitHub produced for a missing repo when prompts are disabled.
    remotes.set_mode(fake_stderr="fatal: could not read Username for 'https://github.com': terminal prompts disabled\n")
    error = fails(remotes, code=ErrorCode.INVALID_REPOSITORY)
    assert "not found" in error.message and "public" in error.message
    assert "Username" not in error.message


def test_empty_repository(remotes):
    remotes.create_empty("example", "portfolio")
    error = fails(remotes, code=ErrorCode.INVALID_REPOSITORY)
    assert "no commits" in error.message


@pytest.mark.parametrize("stderr, code", [
    ("remote: Repository not found.\nfatal: repository 'https://github.com/x/y/' not found", ErrorCode.INVALID_REPOSITORY),
    ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", ErrorCode.INVALID_REPOSITORY),
    ("fatal: Authentication failed for 'https://github.com/x/y.git/'", ErrorCode.INVALID_REPOSITORY),
    ("fatal: unable to access 'https://github.com/x/y.git/': The requested URL returned error: 404", ErrorCode.INVALID_REPOSITORY),
    ("fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host: github.com", ErrorCode.CLONE_FAILED),
    ("fatal: unable to access 'https://github.com/x/y.git/': The requested URL returned error: 503", ErrorCode.CLONE_FAILED),
    ("fatal: the remote end hung up unexpectedly\nfatal: early EOF", ErrorCode.CLONE_FAILED),
    ("", ErrorCode.CLONE_FAILED),
])
def test_stderr_classification(stderr, code):
    assert _classify_failure(stderr).code == code


# --------------------------------------------------------- time and size caps


def test_timeout_kills_git_and_reports_clone_failed(remotes, tmp_path, scratch):
    remotes.create("example", "portfolio", SITE)
    pidfile = tmp_path / "pid"
    remotes.set_mode(sleep_before=30, pidfile=str(pidfile))
    started = time.monotonic()
    error = fails(remotes, code=ErrorCode.CLONE_FAILED, timeout_seconds=1)
    assert time.monotonic() - started < 5
    assert "timed out after 1 seconds" in error.message
    assert not alive(int(pidfile.read_text()))
    assert leftovers(scratch) == []


def test_timeout_kills_the_whole_process_group_not_just_git(remotes, tmp_path):
    remotes.create("example", "portfolio", SITE)
    childfile = tmp_path / "child"
    remotes.set_mode(spawn_sleep=str(childfile))  # wrapper starts a grandchild `sleep 60` and waits on it
    fails(remotes, code=ErrorCode.CLONE_FAILED, timeout_seconds=1)
    assert not alive(int(childfile.read_text()))


def _big_repo(remotes):
    remotes.create("example", "portfolio", {"index.html": "x", "blob.txt": os.urandom(3 * 1024 * 1024)})


def test_size_cap_stops_a_clone_that_is_still_running(remotes):
    _big_repo(remotes)
    remotes.set_mode(sleep_after=20)  # git finishes, wrapper lingers: the watchdog must act first
    started = time.monotonic()
    error = fails(remotes, code=ErrorCode.CLONE_FAILED, max_bytes=1024 * 1024)
    assert time.monotonic() - started < 10
    assert "larger than the 1 MiB clone limit" in error.message


def test_size_cap_also_applies_when_the_clone_finishes_before_the_first_check(remotes):
    _big_repo(remotes)
    error = fails(remotes, code=ErrorCode.CLONE_FAILED, max_bytes=1024 * 1024)
    assert "clone limit" in error.message


def test_normal_sized_repo_is_under_the_default_cap(remotes):
    _big_repo(remotes)
    with clone(remotes) as src:  # default cap is 100 MiB
        assert (src.path / "blob.txt").stat().st_size == 3 * 1024 * 1024


# ------------------------------------------------------------ platform faults


def test_missing_git_binary_is_a_platform_fault_not_a_user_error(scratch):
    with pytest.raises(FileNotFoundError):  # becomes INTERNAL_ERROR via the pipeline guard
        with cloned_source(REPO, git_binary="/nonexistent/git"):
            pass
    assert leftovers(scratch) == []
