"""Safe temporary clone of a public GitHub repository (spec sections 8, 11, 33).

    with cloned_source("https://github.com/owner/repo") as src:
        src.path   # a private temp directory holding the default branch
        src.sha    # the full commit SHA that was cloned
    # on exit the temp directory is deleted, even if the body raised

The repository is untrusted input, so the clone is locked down:

  * Only https://github.com/<owner>/<repo> is accepted (re-checked here even
    though the API already validated it: defence in depth).
  * Public repositories only. Prompts are disabled and credential helpers are
    cleared, so a private or missing repository fails fast instead of waiting
    for a password, and no stored token is ever sent to GitHub.
  * Default branch only, depth 1, no tags, no submodules, no templates.
  * Only the https protocol is allowed (no ext::, file://, ssh).
  * git runs with a clean, minimal environment and its own empty HOME, so
    none of the control plane's secrets are visible to it and no user/system
    git configuration applies.
  * Git LFS downloads are skipped.
  * Wall-clock timeout and a disk-size cap are enforced while git runs; on
    breach the whole process group is killed.
  * Nothing from the repository is executed. `.git` is deleted right after the
    SHA is read so later stages only ever see source files.

Error mapping (the user sees `message`; raw git output only goes to the log):
    bad/unsupported URL, repo missing or not public, repo has no commits
        -> INVALID_REPOSITORY
    timeout, size cap, any other git failure -> CLONE_FAILED
A missing `git` binary is a platform fault and propagates as a plain
exception (the pipeline guard turns it into INTERNAL_ERROR).
"""
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .models import ErrorCode, PipelineError

logger = logging.getLogger(__name__)

_REPO_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$"
)
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

# git stderr fragments that mean "this repository does not exist or is not public".
# GitHub answers identically for both, and with prompts disabled git reports
# "could not read Username" (observed against real GitHub).
_NOT_PUBLIC_MARKERS = (
    "repository not found",
    "could not read username",
    "terminal prompts disabled",
    "authentication failed",
    "returned error: 401",
    "returned error: 404",
    "access blocked",
)

# Environment variables that are safe, and sometimes necessary, to pass on.
_PASSTHROUGH_ENV = (
    "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE",
)

_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class ClonedSource:
    path: Path  # checked-out default branch, no .git directory
    sha: str  # full commit SHA of the cloned HEAD


def _clone_url(repo_url: str) -> str:
    candidate = repo_url.strip().rstrip("/").removesuffix(".git")
    match = _REPO_URL.match(candidate)
    if not match or match.group(2) in {".", ".."}:
        raise PipelineError(
            ErrorCode.INVALID_REPOSITORY,
            "The repository must be a public GitHub repository URL like "
            "https://github.com/<owner>/<repo>.",
        )
    return f"https://github.com/{match.group(1)}/{match.group(2)}.git"


def _git_env(home: Path) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",  # never wait for a password
        "GIT_CONFIG_GLOBAL": os.devnull,  # ignore ~/.gitconfig
        "GIT_CONFIG_NOSYSTEM": "1",  # ignore /etc/gitconfig
        "GIT_LFS_SKIP_SMUDGE": "1",  # never download LFS objects
    }
    for key in _PASSTHROUGH_ENV:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _dir_size(path: Path) -> int:
    """Apparent size in bytes of everything under `path` (symlinks not followed)."""
    total, stack = 0, [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


def _run_clone(
    argv: list[str], env: dict[str, str], dest: Path, stderr_path: Path,
    timeout_seconds: int, max_bytes: int,
) -> tuple[int | None, str | None]:
    """Run git clone under a watchdog. Returns (returncode, abort_reason)."""
    with open(stderr_path, "wb") as stderr:
        proc = subprocess.Popen(
            argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=stderr, start_new_session=True,  # own process group: one kill reaches children
        )
    deadline = time.monotonic() + timeout_seconds
    reason = None
    while True:
        try:
            proc.wait(timeout=_POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pass
        if time.monotonic() > deadline:
            reason = "timeout"
        elif _dir_size(dest) > max_bytes:
            reason = "size"
        if reason:
            _kill_group(proc)
            return proc.returncode, reason
    # A fast clone can finish before the first size poll, so check once more.
    if _dir_size(dest) > max_bytes:
        return proc.returncode, "size"
    return proc.returncode, None


def _read_stderr(path: Path) -> str:
    try:
        raw = path.read_bytes()[-4000:]
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _printable(text: str, limit: int = 500) -> str:
    return "".join(ch if ch.isprintable() or ch == "\n" else "?" for ch in text)[:limit]


def _classify_failure(stderr: str) -> PipelineError:
    lowered = stderr.lower()
    if any(marker in lowered for marker in _NOT_PUBLIC_MARKERS):
        return PipelineError(
            ErrorCode.INVALID_REPOSITORY,
            "Repository not found, or it is not public. "
            "Only public GitHub repositories are supported.",
        )
    return PipelineError(
        ErrorCode.CLONE_FAILED,
        "Could not clone the repository. Check that it exists and that GitHub is "
        "reachable, then deploy again.",
    )


def _head_sha(git: str, repo: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [git, "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        # A successful clone with no resolvable HEAD means an empty repository.
        raise PipelineError(
            ErrorCode.INVALID_REPOSITORY,
            "The repository has no commits. Push your code to the default branch first.",
        )
    sha = result.stdout.strip()
    if not _SHA.match(sha):
        raise PipelineError(ErrorCode.CLONE_FAILED, "Could not determine the source commit.")
    return sha


@contextmanager
def cloned_source(
    repo_url: str,
    *,
    git_binary: str = "git",
    timeout_seconds: int = 60,
    max_bytes: int = 100 * 1024 * 1024,
) -> Iterator[ClonedSource]:
    url = _clone_url(repo_url)
    workdir = Path(tempfile.mkdtemp(prefix="idp-clone-"))  # mode 0700, private to this process
    try:
        home = workdir / "home"
        home.mkdir()
        dest = workdir / "repo"
        env = _git_env(home)
        argv = [
            git_binary,
            "-c", "protocol.allow=never",
            "-c", "protocol.https.allow=always",
            "-c", "credential.helper=",
            "-c", f"core.hooksPath={os.devnull}",
            "clone", "--quiet", "--depth", "1", "--single-branch", "--no-tags",
            "--no-recurse-submodules", "--template=",
            "--", url, str(dest),
        ]
        stderr_path = workdir / "git.stderr"
        returncode, aborted = _run_clone(argv, env, dest, stderr_path, timeout_seconds, max_bytes)

        if aborted == "timeout":
            raise PipelineError(
                ErrorCode.CLONE_FAILED, f"Cloning timed out after {timeout_seconds} seconds."
            )
        if aborted == "size":
            raise PipelineError(
                ErrorCode.CLONE_FAILED,
                f"The repository is larger than the {max_bytes / (1024 * 1024):g} MiB clone limit.",
            )
        if returncode != 0:
            stderr = _read_stderr(stderr_path)
            logger.warning("git clone failed for %s (exit %s): %s", url, returncode, _printable(stderr))
            raise _classify_failure(stderr)

        sha = _head_sha(git_binary, dest, env)
        shutil.rmtree(dest / ".git", ignore_errors=True)
        yield ClonedSource(path=dest, sha=sha)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
