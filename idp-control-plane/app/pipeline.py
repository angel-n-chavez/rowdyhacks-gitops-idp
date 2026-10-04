"""Deployment pipeline orchestration (spec sections 33-35).

PHASE 1 SCAFFOLD. `run_deployment` proves the plumbing end to end (accepted ->
queued -> worker runs it -> status moves -> portal can poll it) and then fails
the deployment on purpose with PIPELINE_NOT_IMPLEMENTED so nobody mistakes it
for a working deploy.

Later phases replace the marked block, in this order:
    Phase 3  clone -> validate -> capture source SHA
    Phase 4  render static manifests -> Git commit/push -> Flux nudge -> observe
    Phase 5  FastAPI: Docker build + registry push before the Git step

`run_guarded` wraps whatever pipeline is plugged in. A platform guarantee, not
a per-pipeline courtesy: if a pipeline crashes, the deployment ends FAILED and
is never left stuck in an in-progress state.
"""
import logging
import uuid
from collections.abc import Callable

from .models import DeploymentStatus, ErrorCode
from .store import Store

logger = logging.getLogger(__name__)


def run_deployment(deployment_id: uuid.UUID, store: Store) -> None:
    store.transition(deployment_id, DeploymentStatus.VALIDATING)

    # ---- replaced in Phases 3-5 ---------------------------------------
    store.fail(
        deployment_id,
        ErrorCode.PIPELINE_NOT_IMPLEMENTED,
        "The deployment pipeline is not implemented yet (Phase 1 scaffold).",
    )
    # -------------------------------------------------------------------


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
