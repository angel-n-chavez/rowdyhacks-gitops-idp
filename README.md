# RowdyHacks GitOps Internal Developer Platform

A hackathon-scale Internal Developer Platform (IDP) prototype. Developers
choose a public GitHub repository and one of two Golden Paths—Static Website or
FastAPI Web Service—through a portal. The intended platform flow packages the
application, records Kubernetes desired state in Git, and uses Flux to deploy
it.

> **Current status:** The portal and Phase 1 control-plane API are available for
> local development. The deployment pipeline is not implemented yet, so
> deployments submitted to the real API currently end in
> `PIPELINE_NOT_IMPLEMENTED`. The portal's mock mode can be used to explore
> the demo UI and simulated deployment lifecycle.

## Repository layout

| Path | Purpose |
|---|---|
| [`portal/`](portal/) | Static developer portal; mock mode and optional control-plane API mode |
| [`idp-control-plane/`](idp-control-plane/) | FastAPI API, in-memory application store, and deployment pipeline scaffold |
| [`idp-gitops-manifests/`](idp-gitops-manifests/) | Flux GitOps state, Golden Path bases, and smoke-test example |
| [`infra/`](infra/) | Terraform and scripts for the initial Vultr infrastructure stage |
| [`ARCHITECTURE-SCHEMA.md`](ARCHITECTURE-SCHEMA.md) | Platform requirements, API contract, and architecture details |

## Run the portal locally

The portal is plain HTML, CSS, and JavaScript; it needs no frontend build step.
From the repository root:

```bash
cd portal
python3 -m http.server 5173
```

Then open <http://localhost:5173/>. This runs the mock demo and requires no
control-plane service.

## Run the control plane locally

In a separate terminal, from the repository root:

```bash
cd idp-control-plane
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
if [ ! -f .env ]; then cp .env.example .env; fi
```

Edit `.env` if needed, then start the API:

```bash
uvicorn app.main:create_app --factory --port 8000 --workers 1
```

The API reads `PLATFORM_DOMAIN` from `.env`. One worker is required because the
application store and job queue are in process memory. Useful endpoints:

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>
- Applications: <http://localhost:8000/apps>

## Connect the portal to the control plane

With the portal served on port 5173 and the API on port 8000, open
<http://localhost:5173/?api>. This opts into the real API; opening the plain
portal URL uses mock data. API mode supports listing applications, details,
deploying, redeploying, and polling status. Logs and deletion are not available
from the control plane yet.

If the API uses a different origin, provide it in the `api` query parameter.
For example, with the API on port 8001:

```text
http://localhost:5173/?api=http%3A%2F%2Flocalhost%3A8001
```

The local API allows browser access from `http://localhost:5173` and
`http://127.0.0.1:5173`. Deploying through the API currently records and
validates the request, then reports `PIPELINE_NOT_IMPLEMENTED`; it does not
build or deploy an application yet.

## Run tests

After installing the control-plane development requirements:

```bash
cd idp-control-plane
pytest
```

## Infrastructure and deployment

The manifests and infrastructure directories are for platform setup and are
not needed to run the local portal or API. See
[`idp-gitops-manifests/README.md`](idp-gitops-manifests/README.md) for the
GitOps layout and
[`idp-control-plane/README.md`](idp-control-plane/README.md) for API details.
Review [`ARCHITECTURE-SCHEMA.md`](ARCHITECTURE-SCHEMA.md) before working on the
deployment pipeline or cluster integration.
