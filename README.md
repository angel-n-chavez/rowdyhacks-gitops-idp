# RowdyHacks GitOps IDP

A hackathon-style Internal Developer Platform (IDP) that lets a developer submit an app intent and have the platform generate and reconcile the deployment workflow through GitOps.

This repository is organized around the core MVP described in [ARCHITECTURE-SCHEMA.md](./ARCHITECTURE-SCHEMA.md): a FastAPI control plane, a Flux-managed GitOps state repository, Terraform infrastructure provisioning, and a developer portal.

## Overview

The goal of this project is simple: give the platform a public GitHub repository and a golden path, and it should return a publicly reachable application URL.

The MVP intentionally does not aim to be production-grade. It is designed as a proof-of-concept for platform engineering patterns:

- Developer enters app intent instead of writing Kubernetes or Docker config
- A small set of supported golden paths controls validation
- The control plane generates deployment manifests
- Flux reconciles generated application state from Git
- Traefik exposes the application through a public hostname

## Project structure

- [idp-control-plane](./idp-control-plane) — FastAPI control plane that validates repositories, stages deployment jobs, and writes GitOps manifests
- [idp-gitops-manifests](./idp-gitops-manifests) — GitOps repository watched by Flux for deployed app state
- [infra](./infra) — Terraform and Vultr bootstrap scripts for the platform infrastructure
- [portal](./portal) — developer-facing portal UI
- [ARCHITECTURE-SCHEMA.md](./ARCHITECTURE-SCHEMA.md) — implementation contract and architecture requirements

## Supported golden paths

The MVP supports two deployment patterns:

- `static` — deploys a static site built from HTML/CSS/JS assets
- `fastapi` — deploys a Python FastAPI app with a root-level `main.py` and `requirements.txt`

The control plane validates repository structure and content before proceeding. It does not execute project code during validation.

## Core system flow

1. Developer submits deployment intent via the API or portal
2. The control plane clones the public GitHub repository
3. The repository is validated against the selected golden path
4. The platform renders Kubernetes manifests for the app
5. The control plane commits the generated state to the GitOps repo
6. Flux synchronizes the app into the cluster
7. Traefik routes traffic to the app using a generated hostname

## Quick start

### Control plane

```bash
cd idp-control-plane
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
pytest
uvicorn app.main:create_app --factory --port 8000 --workers 1
```

API docs are available at:

- http://localhost:8000/docs

### GitOps manifests

The GitOps repo is intended to be reconciled by Flux. See [idp-gitops-manifests/README.md](./idp-gitops-manifests/README.md) for the state-repo contract and validation steps.

### Infrastructure

Terraform and cloud bootstrap scripts live under [infra](./infra). That layer provisions the platform infrastructure and base cluster dependencies.

## Documentation

- [ARCHITECTURE-SCHEMA.md](./ARCHITECTURE-SCHEMA.md) — architecture and constraints for the MVP
- [idp-control-plane/README.md](./idp-control-plane/README.md) — detailed control plane setup and validation rules
- [idp-gitops-manifests/README.md](./idp-gitops-manifests/README.md) — GitOps repo layout and Flux workflow

## Notes

This project is intentionally scoped to a demo-friendly MVP and should not be treated as production-ready. It follows the repository security rule from the architecture docs: no secrets, keys, kubeconfigs, or credentials are meant to be committed anywhere in the repo.

## License

This repository does not currently declare a project license. Add one if you plan to distribute or reuse the code beyond the hackathon context.
