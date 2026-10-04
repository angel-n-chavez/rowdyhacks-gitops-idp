# idp-control-plane

FastAPI control plane for the RowdyHacks GitOps IDP. Architecture contract:
`../ARCHITECTURE-SCHEMA.md`. Build status: **Phase 3 (clone + Golden Path validation)**.
Repositories are cloned and validated for real; what happens *after* a repository
passes (manifests, build, deploy) is Phases 4-5, so for now a valid repository
ends `failed` with `PIPELINE_NOT_IMPLEMENTED` on purpose.

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
* `git` must be installed on the machine running the control plane.
* The default test run is **offline**: git runs against local fixture repositories
  that stand in for github.com. To also check the real thing (public GitHub
  repositories, no wrapper): `pytest -m network`.

## Database

Two tables, spec section 14: `applications` and `deployments`. Created at
startup with `create_all`, which **only creates missing tables**. If a column
is ever added, an existing database needs a manual `ALTER TABLE` (or a drop
and recreate while developing). Alembic is deliberately not used yet.

## What a repository must satisfy

Cloning: public `https://github.com/<owner>/<repo>`, default branch only, no
credentials. Limits: 60 s and 100 MiB (`CLONE_TIMEOUT_SECONDS`, `CLONE_MAX_MIB`).
Nothing from a repository is ever executed during validation.

**static** (`error_code`: `GOLDEN_PATH_VIOLATION`, or `STATIC_SITE_TOO_LARGE`)

* `index.html` at the repository root
* only `.html .css .js .json .svg .txt` files (so no PNG/JPG/fonts: use SVG)
* names use only letters, digits, `.` `_` `-`, and don't start with `.`
* UTF-8 text, no symbolic links
* at most 900 KiB and 500 files in total
* `README*`, `LICENSE*`, `.gitignore`, `.github/` etc. are ignored, not deployed

**fastapi** (`GOLDEN_PATH_VIOLATION`)

* `main.py` and `requirements.txt` at the repository root (regular files)
* `main.py` exposes `app` at module level (checked by reading the code, e.g.
  `app = FastAPI()`; factory functions are not supported)

Clone problems use `INVALID_REPOSITORY` (not found / not public / empty) or
`CLONE_FAILED` (timeout, too large, GitHub unreachable).

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | unauthenticated |
| POST | `/deploy` | `202` + `deployment_id`; unknown fields are `422` |
| GET | `/apps` | summaries |
| GET | `/apps/{app_name}` | detail + latest deployment |

Logs and delete arrive in Phase 6; auth and CORS in Phase 7.
