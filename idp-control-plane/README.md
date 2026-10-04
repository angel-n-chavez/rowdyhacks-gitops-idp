# idp-control-plane

FastAPI control plane for the RowdyHacks GitOps IDP. Architecture contract:
`../ARCHITECTURE-SCHEMA.md`. Build status: **Phase 2 (PostgreSQL)**. The
deployment pipeline is still a scaffold that fails on purpose with
`PIPELINE_NOT_IMPLEMENTED` until Phases 3-5.

## Run locally

```bash
docker compose up -d db              # PostgreSQL 16 on localhost:5432
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # DATABASE_URL, PLATFORM_DOMAIN
pytest
uvicorn app.main:create_app --factory --port 8000 --workers 1
```

* `--workers 1` is required: the job queue lives inside the process, and on
  startup any deployment still "in progress" is failed as orphaned.
* Tests use a separate database, `idp_test` (created automatically; override
  with `TEST_DATABASE_URL`). Its name must end in `_test` because every test
  truncates the tables. Tests need a real PostgreSQL and stop with
  instructions if there isn't one; they never silently skip.
* Interactive docs: http://localhost:8000/docs

## Database

Two tables, spec section 14: `applications` and `deployments`. Created at
startup with `create_all`, which **only creates missing tables**. If a column
is ever added, an existing database needs a manual `ALTER TABLE` (or a drop
and recreate while developing). Alembic is deliberately not used yet.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | unauthenticated |
| POST | `/deploy` | `202` + `deployment_id`; unknown fields are `422` |
| GET | `/apps` | summaries |
| GET | `/apps/{app_name}` | detail + latest deployment |

Logs and delete arrive in Phase 6; auth and CORS in Phase 7.
