# idp-control-plane

FastAPI control plane for the RowdyHacks GitOps IDP. Architecture contract:
`../ARCHITECTURE-SCHEMA.md`. Build status: **Phase 1 (API contract)**. The
deployment pipeline is a scaffold that fails on purpose with
`PIPELINE_NOT_IMPLEMENTED` until Phases 3-5.

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # set PLATFORM_DOMAIN
pytest
uvicorn app.main:create_app --factory --port 8000 --workers 1
```

`--workers 1` is required: the store and job queue live inside the process.
Interactive docs: http://localhost:8000/docs

## Endpoints (Phase 1)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | unauthenticated |
| POST | `/deploy` | `202` + `deployment_id`; unknown fields are `422` |
| GET | `/apps` | summaries |
| GET | `/apps/{app_name}` | detail + latest deployment |

Logs and delete arrive in Phase 6; auth and CORS in Phase 7.
