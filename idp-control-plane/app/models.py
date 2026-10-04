"""API contract (spec sections 9-14, 25-28, 36).

Pydantic models for requests/responses, the deployment status enum, the
state machine, and the error codes. No I/O happens here.
"""
import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class GoldenPath(StrEnum):
    STATIC = "static"
    FASTAPI = "fastapi"


class DeploymentStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    BUILDING = "building"
    DEPLOYING = "deploying"
    RUNNING = "running"
    CRASHING = "crashing"
    FAILED = "failed"


# The portal keeps polling while a deployment is in one of these.
IN_PROGRESS = frozenset(
    {
        DeploymentStatus.PENDING,
        DeploymentStatus.VALIDATING,
        DeploymentStatus.BUILDING,
        DeploymentStatus.DEPLOYING,
    }
)


class ErrorCode(StrEnum):
    # Spec section 36
    INVALID_REPOSITORY = "INVALID_REPOSITORY"
    CLONE_FAILED = "CLONE_FAILED"
    GOLDEN_PATH_VIOLATION = "GOLDEN_PATH_VIOLATION"
    STATIC_SITE_TOO_LARGE = "STATIC_SITE_TOO_LARGE"
    BUILD_FAILED = "BUILD_FAILED"
    REGISTRY_PUSH_FAILED = "REGISTRY_PUSH_FAILED"
    GITOPS_FAILED = "GITOPS_FAILED"
    FLUX_TIMEOUT = "FLUX_TIMEOUT"
    DEPLOYMENT_TIMEOUT = "DEPLOYMENT_TIMEOUT"
    RUNTIME_CRASH = "RUNTIME_CRASH"
    APP_NOT_FOUND = "APP_NOT_FOUND"
    # Additions
    GOLDEN_PATH_CONFLICT = "GOLDEN_PATH_CONFLICT"  # redeploy with a different Golden Path
    INTERNAL_ERROR = "INTERNAL_ERROR"  # unexpected platform bug; details go to logs only
    PIPELINE_NOT_IMPLEMENTED = "PIPELINE_NOT_IMPLEMENTED"  # Phase 1 scaffold; removed in Phase 3/4


# --------------------------------------------------------------------------
# State machine (spec section 13)
# --------------------------------------------------------------------------

_S = DeploymentStatus

_COMMON = {
    # DEPLOYING -> CRASHING is not in the section 13 diagram but IS in the
    # section 34/35 pipelines (a first deploy can hit ImagePullBackOff).
    _S.DEPLOYING: {_S.RUNNING, _S.CRASHING, _S.FAILED},
    _S.RUNNING: {_S.CRASHING},
    _S.CRASHING: {_S.RUNNING},
    _S.FAILED: set(),
}

_TRANSITIONS: dict[GoldenPath, dict[DeploymentStatus, set[DeploymentStatus]]] = {
    GoldenPath.STATIC: {
        _S.PENDING: {_S.VALIDATING},
        _S.VALIDATING: {_S.DEPLOYING, _S.FAILED},  # static skips BUILDING
        **_COMMON,
    },
    GoldenPath.FASTAPI: {
        _S.PENDING: {_S.VALIDATING},
        _S.VALIDATING: {_S.BUILDING, _S.FAILED},
        _S.BUILDING: {_S.DEPLOYING, _S.FAILED},
        **_COMMON,
    },
}


def transition_allowed(path: GoldenPath, current: DeploymentStatus, new: DeploymentStatus) -> bool:
    if current == new:
        return True  # no-op
    return new in _TRANSITIONS[path].get(current, set())


# --------------------------------------------------------------------------
# Request models (spec sections 10-11, layer 1 validation)
# --------------------------------------------------------------------------

# Spec section 10 recommends this regex, but on its own it accepts a 1-character
# name. The spec also says 3-30 characters, so length is enforced separately.
APP_NAME_PATTERN = r"^[a-z0-9](?:[-a-z0-9]{1,28}[a-z0-9])?$"
AppName = Annotated[str, Field(min_length=3, max_length=30, pattern=APP_NAME_PATTERN)]

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _github_owner_repo(url: HttpUrl) -> tuple[str, str]:
    """Validate `https://github.com/<owner>/<repo>[.git]` and return (owner, repo)."""
    if url.scheme != "https":
        raise ValueError("repository must use https")
    if url.host != "github.com":
        raise ValueError("repository host must be exactly github.com")
    if url.username or url.password:
        raise ValueError("repository URL must not contain credentials")
    if url.port not in (None, 443):
        raise ValueError("repository URL must not specify a port")
    if url.query or url.fragment:
        raise ValueError("repository URL must not contain a query string or fragment")
    parts = [p for p in (url.path or "").strip("/").split("/") if p != ""]
    if len(parts) != 2:
        raise ValueError(
            "repository must look like https://github.com/<owner>/<repo> "
            "(the default branch is always used)"
        )
    owner, repo = parts
    repo = repo.removesuffix(".git")
    if not _OWNER_RE.match(owner) or not _REPO_RE.match(repo) or repo in {".", ".."}:
        raise ValueError("repository owner or name contains invalid characters")
    return owner, repo


def _check_repo(url: HttpUrl) -> HttpUrl:
    _github_owner_repo(url)
    return url


GitHubRepoUrl = Annotated[HttpUrl, AfterValidator(_check_repo)]


def canonical_repo_url(url: HttpUrl) -> str:
    """Stable form we store and return: https://github.com/<owner>/<repo>."""
    owner, repo = _github_owner_repo(url)
    return f"https://github.com/{owner}/{repo}"


class _DeployBase(BaseModel):
    # Anything not listed (env, port, replicas, image, namespace, ...) is a 422.
    model_config = ConfigDict(extra="forbid")

    name: AppName
    repository: GitHubRepoUrl


class StaticDeployRequest(_DeployBase):
    golden_path: Literal["static"]


class FastAPIDeployRequest(_DeployBase):
    golden_path: Literal["fastapi"]


DeployRequest = Annotated[
    Union[StaticDeployRequest, FastAPIDeployRequest],
    Field(discriminator="golden_path"),
]

# --------------------------------------------------------------------------
# Response models (spec sections 12, 27, 28)
# --------------------------------------------------------------------------


def public_deployment_id(raw: uuid.UUID) -> str:
    """API-facing id (`dep_<hex>`). The database stores the plain UUID."""
    return f"dep_{raw.hex}"


class DeployAccepted(BaseModel):
    deployment_id: str
    app_name: str
    status: DeploymentStatus
    message: str = "Deployment accepted"


class DeploymentOut(BaseModel):
    deployment_id: str
    status: DeploymentStatus
    source_revision: str | None = None
    image_tag: str | None = None
    gitops_commit: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AppSummary(BaseModel):
    name: str
    golden_path: GoldenPath
    repository: str
    status: DeploymentStatus
    live_url: str
    updated_at: datetime


class AppDetail(AppSummary):
    namespace: str
    latest_deployment: DeploymentOut | None = None
