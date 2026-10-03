# idp-control-plane

FastAPI control plane for the mini-IDP ("mini-Heroku"). A developer POSTs JSON; the platform
clones their repo, checks it against a **Golden Path**, injects its own Dockerfile, builds and
pushes the image, commits a tiny Kustomize overlay to the GitOps repo, and nudges Flux.

> **Rehearsal build.** This is a dry-run version targeting a Proxmox + k3s homelab so the
> pipeline can be tested before the hackathon. See `HOMELAB-DRYRUN.md`.

## Flow
```
POST /deploy
  1. validate payload                 -> 422 on bad name / repo URL / env vars
  2. git clone --depth 1 (https only) -> 400 clone_failed
  3. golden-path check                -> 400 golden_path_violation   (all of 1-3 are synchronous)
  4. 202 + job id; then in the background:
  5. inject platform Dockerfile, docker build, docker push
  6. render apps-prod/<app>/kustomization.yaml, commit + push (under a lock)
  7. flux reconcile kustomization apps --with-source   (skip the 15s wait)
```

## Layout
```
app/main.py         endpoints, status-code mapping
app/models.py       payload validation (name regex, repo allow-list, env var rules)
app/golden_path.py  compliance checks (reads files, never executes repo code)
app/clone.py        hardened shallow clone
app/builder.py      template injection + Docker SDK build/push
app/overlay.py      dict -> kustomization.yaml (the whole Python<->cluster interface)
app/gitops.py       GitPython: sync/commit/push under a lock, retries
app/flux.py         force reconcile via the flux CLI
app/k8s.py          read-only status / logs / events (kubernetes client)
app/jobs.py         in-memory job tracker
app/pipeline.py     background worker
app/agents.py       OPTIONAL Gemini agents (ops assistant + troubleshooter)
app/templates/      immutable Dockerfiles (+ nginx.conf) per app type
runbooks/           fed to the troubleshooting agent as context
examples/           demo repos (compliant web, compliant static, non-compliant)
tests/              82 tests (see below)
scripts/smoke.sh    end-to-end check against a live deployment
```

## Endpoints (all but /healthz need `X-API-Key`)
| Method | Path | Notes |
|---|---|---|
| POST | `/deploy[?wait=true]` | 202 + job (poll), or block until done: 200 ok / 500 failed |
| GET | `/deployments`, `/deployments/{id}` | job state, stage, logs |
| GET | `/apps`, `/apps/{name}/status`, `/apps/{name}/logs` | live cluster state |
| DELETE | `/apps/{name}` | `git rm` the overlay; Flux prunes |
| POST | `/admin/reconcile` | force a Flux sync |
| POST | `/agents/ops`, `/agents/troubleshoot` | Gemini (503 if no key) |

Status codes: `401` auth, `422` malformed payload, `400` repo fails clone / Golden Path,
`409` that app is already deploying, `503` cluster unreachable or agents disabled.

## Golden Path
| `app_type` | repo must have | platform supplies |
|---|---|---|
| `web-service` | `requirements.txt` listing fastapi; `main.py` defining/importing `app` | `python:3.12-slim`, `uvicorn main:app --host 0.0.0.0 --port 8080`, `USER 10001` |
| `static-site` | `index.html` in root | `nginx-unprivileged`, own `nginx.conf` on 8080, `USER 10001` |

## Run
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
GITOPS_MANIFESTS_DIR=../idp-gitops-manifests pytest -q      # kustomize on PATH enables the contract test
cp .env.example .env && $EDITOR .env
set -a; . ./.env; set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1  # ONE worker: the git lock is in-process
# open http://<host>:8000/docs -> Authorize -> paste IDP_API_KEY
```

## Design notes
* **Lock**: only the git sync/commit/push section is serialised; builds run in parallel (capped at 1 at a time).
* **Never trusts the repo**: symlinks rejected, template files are deleted before copy (no write-through), no repo code is executed outside `docker build`.
* **Secrets**: env vars land as a plaintext ConfigMap in the (private) GitOps repo. SOPS/age is the planned next step.

## Known limitations (PoC)
In-memory jobs (lost on restart) · single process · HTTP only (put TLS in front for real use) ·
public GitHub repos only · no per-app resource quotas · no auth separation between developers and admins.
