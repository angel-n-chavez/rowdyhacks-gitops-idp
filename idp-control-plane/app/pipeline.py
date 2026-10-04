"""Deployment pipeline orchestration (spec sections 33-35).

Implemented so far (Phase 3):

    PENDING -> VALIDATING -> clone -> record source commit -> validate Golden Path

Both Golden Paths currently stop right after validation. Later phases extend
this at the marked block, in this order:

    Phase 4  static:  render manifests -> Git commit/push -> Flux -> observe
    Phase 5  fastapi: Docker build + registry push before the Git step

Until then a repository that PASSES validation still ends FAILED with
PIPELINE_NOT_IMPLEMENTED, on purpose, so nobody mistakes the scaffold for a
working deploy (the recorded source_revision shows it got that far). Moving a
deployment into BUILDING/DEPLOYING would claim work that does not happen.

`run_guarded` wraps whatever pipeline is plugged in. A platform guarantee, not
a per-pipeline courtesy: if a pipeline crashes, the deployment ends FAILED and
is never left stuck in an in-progress state.
"""
import logging
import uuid
from collections.abc import Callable

from .clone import cloned_source
from .config import Settings
from .golden_path import validate
from .models import DeploymentStatus, ErrorCode, PipelineError
from .store import Store

logger = logging.getLogger(__name__)


def run_deployment(deployment_id: uuid.UUID, store: Store, *, settings: Settings) -> None:
    deployment = store.get_deployment(deployment_id)
    application = store.get_application_by_id(deployment.application_id)
    store.transition(deployment_id, DeploymentStatus.VALIDATING)

    try:
        with cloned_source(
            application.repository_url,
            git_binary=settings.git_binary,
            timeout_seconds=settings.clone_timeout_seconds,
            max_bytes=settings.clone_max_mib * 1024 * 1024,
        ) as source:
            # Record the commit as soon as we have it, so even a repository that
            # fails validation shows exactly which commit was inspected.
            store.update_fields(deployment_id, source_revision=source.sha)
            validate(application.golden_path, source.path)

            # ---- replaced in Phases 4-5 -----------------------------------
            store.transition(
                deployment_id,
                DeploymentStatus.FAILED,
                error_code=ErrorCode.PIPELINE_NOT_IMPLEMENTED.value,
                error_message=(
                    f"Repository validated successfully (commit {source.sha[:7]}), but the "
                    "build/deploy stages are not implemented yet."
                ),
            )
            # ---------------------------------------------------------------
    except PipelineError as exc:
        store.transition(
            deployment_id,
            DeploymentStatus.FAILED,
            error_code=exc.code.value,
            error_message=exc.message,
        )


def run_guarded(
    pipeline: Callable[[uuid.UUID, Store], None], deployment_id: uuid.UUID, store: Store
) -> None:
    try:
        pipeline(deployment_id, store)
    except Exception:
        # Full detail goes to the log only: error_message is shown to
        # developers, so it must never carry raw internals (spec section 36).
        logger.exception("pipeline crashed for deployment %s", deployment_id)
        try:
            store.fail(
                deployment_id,
                ErrorCode.INTERNAL_ERROR,
                "Unexpected platform error. See the control-plane logs for details.",
            )
        except Exception:
            logger.exception("could not record failure for deployment %s", deployment_id)
