# RowdyHacks 2026 --- GitOps Internal Developer Platform

## Architecture & Implementation Schema

**Project:** RowdyHacks GitOps IDP\
**Status:** MVP architecture locked for implementation\
**Primary cloud:** Vultr Cloud\
**Infrastructure:** Terraform\
**Control plane:** FastAPI / Python\
**Runtime:** Vultr Kubernetes Engine (VKE)\
**GitOps:** FluxCD\
**Ingress:** Traefik\
**Database:** PostgreSQL\
**Container registry:** Private Vultr Container Registry

> This document is the implementation contract for the MVP. Claude
> should implement this architecture rather than redesign it. Use MUST /
> SHOULD / MAY literally. Prefer the smallest implementation that
> satisfies the MUST requirements.

------------------------------------------------------------------------

# 1. Product Goal

Build a small Internal Developer Platform (IDP) that allows a developer
to deploy an application without writing Dockerfiles, Kubernetes YAML,
Terraform, or ingress configuration.

The developer provides only application intent:

``` json
{
  "name": "weather-api",
  "golden_path": "fastapi",
  "repository": "https://github.com/example/weather-api"
}
```

The platform owns packaging, image creation where required, Kubernetes
desired state, GitOps commits, routing, deployment status, and cleanup.

The core demo promise is:

> Give the platform a public GitHub repository and a Golden Path. The
> platform returns a publicly reachable application URL.

This is a hackathon proof of concept modeled after real
platform-engineering patterns. It MUST NOT be described as
production-ready.

------------------------------------------------------------------------

# 2. Architectural Principles

The MVP MUST follow these principles:

1.  **Developer intent, not infrastructure configuration.**
2.  **Exactly two Golden Paths:** `static` and `fastapi`.
3.  Developers MUST NOT submit Dockerfiles, Kubernetes manifests,
    namespaces, ports, replicas, image names, resource limits, or
    ingress settings through the API.
4.  Git MUST be the source of truth for Kubernetes application desired
    state.
5.  FluxCD MUST reconcile application state from Git.
6.  Terraform MUST provision the Vultr infrastructure and bootstrap the
    platform infrastructure.
7.  The control plane MUST NOT directly create application
    Deployments/Services/IngressRoutes as its normal deployment
    mechanism.
8.  The control plane MAY use Kubernetes access for status, logs, and a
    best-effort Flux reconciliation nudge.
9.  The platform MUST expose applications through Traefik using
    generated hostnames.
10. The MVP SHOULD remain intentionally small. Do not add production
    systems unless required by this document.

------------------------------------------------------------------------

# 3. Non-Goals / Out of Scope

Do NOT add these to the MVP critical path:

-   GitHub OAuth
-   private developer source repositories
-   GitHub webhooks
-   automatic redeploy-on-push
-   custom developer Dockerfiles
-   custom Kubernetes YAML
-   custom domains
-   multi-cluster support
-   autoscaling
-   multiple replicas
-   Celery, Kafka, RabbitMQ, or another external job queue
-   SOPS implementation
-   external secret managers
-   full multi-user RBAC
-   service mesh
-   AI agents
-   production build isolation
-   production-grade observability stack
-   canary or blue/green deployment
-   arbitrary Python frameworks
-   Node.js Golden Path

These MAY be documented as future work.

------------------------------------------------------------------------

# 4. Repository Model

The RowdyHacks MVP MUST use **one public GitHub repository** for both
submission source and GitOps desired state:

``` text
rowdyhacks-gitops-idp/
├── ARCHITECTURE-SCHEMA.md
├── idp-control-plane/
├── idp-gitops-manifests/
├── infra/
└── portal/
```

Responsibilities:

-   `idp-control-plane/` contains FastAPI code, validation, build logic,
    GitOps generation logic, and platform-owned templates.
-   `idp-gitops-manifests/` contains the **actual rendered Kubernetes
    desired state** reconciled by Flux during the demo.
-   `infra/` contains Terraform and Vultr bootstrap code.
-   `portal/` contains the developer portal.

Flux MUST use this same public repository as its Git source and
reconcile:

``` text
./idp-gitops-manifests
```

The control plane MUST commit generated application state back to the
same public repository. During normal application deployment, its Git
write boundary is:

``` text
idp-gitops-manifests/apps/**
```

It MUST NOT modify control-plane source, Terraform, portal code,
`clusters/**`, or `infrastructure/**` as part of an application
deployment.

This is intentional: judges can inspect the generated desired state and
Git audit trail during the demo.

Templates MUST remain under:

``` text
idp-control-plane/app/templates/
```

`idp-gitops-manifests/` contains rendered desired state only.

## Public repository security rule

Because the repository is public, **no credentials, API keys,
application secrets, registry passwords, GitHub tokens, kubeconfigs,
Terraform secrets, or other sensitive values may ever be committed
anywhere in it.**

The MVP `/deploy` API therefore MUST NOT accept developer environment
variables or secrets.

Applications used for the MVP demo MUST run without secret
configuration.

Developer-managed environment variables become future work after a
secure mechanism such as SOPS/age or External Secrets is added.

# 5. Target System Architecture

``` text
Developer Portal
       |
       | HTTP/JSON
       v
FastAPI Control Plane (Vultr Debian VM)
       |
       +--> PostgreSQL
       |
       +--> clone public GitHub source repo
       |
       +--> validate Golden Path
       |
       +--> [FastAPI only] Docker SDK build
       |                         |
       |                         v
       |                Vultr Container Registry
       |
       +--> render Kubernetes manifests
       |
       +--> commit/push
       v
Public RowdyHacks Repository
(idp-gitops-manifests/)
       |
       | Flux reconciliation (~15s)
       v
Vultr Kubernetes Engine
       |
       +--> application Namespace
       +--> Deployment
       +--> Service
       +--> Traefik IngressRoute
       |
       v
Public application URL
```

The public URL is a hard MVP requirement. SSH access is not part of the
demo path.

------------------------------------------------------------------------

# 6. Terraform / Vultr Infrastructure

Infrastructure is not assumed to exist before application development.

Terraform MUST be the reproducible infrastructure entry point.

## Stage 1 --- Vultr resources

Terraform Stage 1 MUST provision the required Vultr resources:

-   Debian control-plane VM
-   Vultr Kubernetes Engine cluster
-   private Vultr Container Registry
-   required Vultr firewall configuration
-   outputs required by later stages

The existing canonical Vultr code is under:

``` text
infra/vultr/stage1/
```

Proxmox infrastructure is rehearsal/homelab code and is NOT part of the
RowdyHacks deployment architecture.

## Stage 2 --- platform bootstrap

Terraform Stage 2 MUST use the generated VKE kubeconfig to bootstrap:

-   FluxCD
-   Traefik
-   GitOps source configuration
-   Flux Kustomizations required for infrastructure and applications

The existing Stage 2 directory is:

``` text
infra/stage2/
```

Infrastructure MUST be reproducible from the user's laptop with
Terraform.

Terraform secrets and credentials MUST NOT be committed.

------------------------------------------------------------------------

# 7. GitOps Path Structure

Within the public repository:

``` text
idp-gitops-manifests/
├── clusters/
│   └── vke-prod/
│       ├── flux-system/
│       ├── infrastructure.yaml
│       └── apps.yaml
├── infrastructure/
│   └── traefik/
│       ├── namespace.yaml
│       ├── helmrepository.yaml
│       ├── helmrelease.yaml
│       └── kustomization.yaml
└── apps/
    ├── static/
    │   ├── kustomization.yaml
    │   └── <app-name>/
    │       ├── namespace.yaml
    │       ├── configmap.yaml
    │       ├── deployment.yaml
    │       ├── service.yaml
    │       ├── ingressroute.yaml
    │       └── kustomization.yaml
    └── fastapi/
        ├── kustomization.yaml
        └── <app-name>/
            ├── namespace.yaml
            ├── deployment.yaml
            ├── service.yaml
            ├── ingressroute.yaml
            └── kustomization.yaml
```

Every application directory MUST be a self-contained Kustomize unit.

The control plane MAY update:

``` text
apps/**
```

This includes the appropriate parent `apps/static/kustomization.yaml` or
`apps/fastapi/kustomization.yaml` when adding/removing an app.

The control plane MUST NOT modify during normal app deployment:

``` text
clusters/**
infrastructure/**
clusters/**/flux-system/**
```

Flux infrastructure MUST reconcile before application state.

------------------------------------------------------------------------

# 8. Golden Path Contract

There are exactly two Golden Paths.

## 8.1 Static Golden Path

Canonical request:

``` json
{
  "name": "portfolio",
  "golden_path": "static",
  "repository": "https://github.com/example/portfolio"
}
```

The source repository MUST:

-   be a publicly cloneable GitHub repository
-   use its default branch
-   contain `index.html`
-   contain deployable text/static assets only
-   remain below the platform ConfigMap size threshold

For the MVP, supported deployable extensions SHOULD be restricted to:

``` text
.html
.css
.js
.json
.svg
.txt
```

The total rendered ConfigMap content MUST be limited to approximately
**900 KiB** to leave headroom below the Kubernetes ConfigMap object
limit.

The platform MUST reject unsafe paths and path traversal.

The platform SHOULD preserve nested static paths by mapping safe
ConfigMap keys to volume item paths.

The platform owns:

-   namespace
-   ConfigMap
-   Nginx runtime
-   Deployment
-   Service
-   Traefik IngressRoute
-   hostname
-   Kustomization
-   Git commit
-   Flux reconciliation
-   status

There is NO Docker build for this Golden Path.

## 8.2 FastAPI Golden Path

Canonical request:

``` json
{
  "name": "weather-api",
  "golden_path": "fastapi",
  "repository": "https://github.com/example/weather-api"
}
```

Optional environment variables:

``` json
{
  "name": "weather-api",
  "golden_path": "fastapi",
  "repository": "https://github.com/example/weather-api",
  "env": {
    "WEATHER_API_KEY": "example-value",
    "LOG_LEVEL": "INFO"
  }
}
```

The source repository MUST:

-   be a publicly cloneable GitHub repository
-   use its default branch
-   contain `main.py`
-   contain `requirements.txt`
-   expose a FastAPI application as `main:app`

The platform MUST own:

-   Python Alpine runtime template
-   Uvicorn runtime
-   Dockerfile
-   build command
-   internal container port
-   image naming/tagging
-   namespace
-   Deployment
-   Service
-   Traefik IngressRoute
-   hostname
-   Kustomization
-   Git commit
-   Flux reconciliation
-   status

The runtime command is platform-defined:

``` text
uvicorn main:app --host 0.0.0.0 --port 8000
```

Uvicorn SHOULD be installed by the platform Docker template rather than
requiring the developer to duplicate it in the API request.

Developer dependencies remain in `requirements.txt`.

------------------------------------------------------------------------

# 9. Tiny API Contract

The API surface is intentionally small.

``` text
GET     /health
POST    /deploy
GET     /apps
GET     /apps/{app_name}
GET     /apps/{app_name}/logs
DELETE  /apps/{app_name}
```

There is NO `/redeploy` endpoint.

Calling `POST /deploy` with an existing application name creates a new
deployment attempt for that application.

------------------------------------------------------------------------

# 10. Request Models

Use Pydantic V2 with a discriminated union on `golden_path`.

Conceptually:

``` python
StaticDeployRequest:
    name: str
    golden_path: Literal["static"]
    repository: HttpUrl

FastAPIDeployRequest:
    name: str
    golden_path: Literal["fastapi"]
    repository: HttpUrl
```

The developer-facing API is intentionally tiny.

Models MUST reject unknown fields (`extra="forbid"`).

There is no `env`, `port`, `replicas`, `python_version`, `requirements`,
`namespace`, `hostname`, `image`, Dockerfile, or Kubernetes
configuration in the MVP request.

## Application name

`name` MUST be lowercase, use only `a-z`, `0-9`, and `-`, begin and end
with an alphanumeric character, be DNS-label compatible, and be between
3 and 30 characters.

Recommended regex:

``` text
^[a-z0-9](?:[-a-z0-9]{1,28}[a-z0-9])?$
```

Do NOT silently lowercase invalid names.

## Repository URL

The repository MUST use HTTPS, have host `github.com`, represent a
public repository, and contain no embedded credentials.

The control plane MUST clone the repository's default branch only.
Branch selection is out of scope for MVP.

## Secrets and environment variables

The MVP API MUST NOT accept developer-provided environment variables or
secrets.

This restriction exists because the RowdyHacks GitOps state is
intentionally public and judge-visible.

Secret injection is future work and MUST NOT be improvised by committing
plaintext values.

# 11. Request Validation vs Repository Validation

These are separate layers.

## Layer 1 --- API/Pydantic validation

Invalid API shape MUST be rejected before a deployment job starts.

Examples:

-   invalid app name
-   unsupported Golden Path
-   non-GitHub URL
-   malformed URL
-   unexpected fields
-   invalid environment variable names

FastAPI's normal validation response MAY be used with HTTP
`422 Unprocessable Entity`.

No clone/build/GitOps action should occur.

## Layer 2 --- Golden Path repository validation

After request acceptance, the background pipeline clones and validates
repository contents.

Static validation MUST verify:

-   `index.html`
-   supported file types
-   safe relative paths
-   size limit

FastAPI validation MUST verify:

-   `main.py`
-   `requirements.txt`
-   expected `app` symbol/contract

Repository validation MUST NOT import and execute arbitrary developer
application code merely to discover whether `app` exists. A simple
AST/text-based validation is preferred for the MVP.

A repository contract failure transitions the deployment to `FAILED`.

------------------------------------------------------------------------

# 12. POST /deploy Behavior

`POST /deploy` MUST be asynchronous from the caller's perspective.

After request-level validation and creation of the database records/job,
it MUST return:

``` http
HTTP/1.1 202 Accepted
```

Example response:

``` json
{
  "deployment_id": "dep_01J...",
  "app_name": "weather-api",
  "status": "validating",
  "message": "Deployment accepted"
}
```

If the implementation briefly creates the job as `pending`, returning
`pending` is acceptable. The frontend MUST treat both `pending` and
`validating` as in-progress.

The request MUST NOT wait for Docker, GitOps, Flux, or Kubernetes
convergence.

------------------------------------------------------------------------

# 13. Deployment State Machine

A state machine is simply the allowed lifecycle of a deployment.

## FastAPI

``` text
PENDING
   |
   v
VALIDATING
   |
   v
BUILDING
   |
   v
DEPLOYING
   |
   v
RUNNING
```

## Static

``` text
PENDING
   |
   v
VALIDATING
   |
   v
DEPLOYING
   |
   v
RUNNING
```

Failures:

``` text
VALIDATING ---> FAILED
BUILDING   ---> FAILED
DEPLOYING  ---> FAILED
```

Runtime problems:

``` text
RUNNING ---> CRASHING
CRASHING ---> RUNNING
```

`FAILED` means the platform pipeline could not successfully
complete/converge.

`CRASHING` means the workload exists in Kubernetes but is unhealthy,
restarting, or unable to start correctly.

Frontend-level canonical statuses:

``` text
pending
validating
building
deploying
running
crashing
failed
```

Deletion MAY introduce `deleting` internally/UI-side if useful, but it
is not required for the initial deployment path.

------------------------------------------------------------------------

# 14. PostgreSQL Schema

Use PostgreSQL, not SQLite.

Keep the schema minimal.

## applications

Required logical columns:

``` text
id                  UUID primary key
name                VARCHAR unique not null
golden_path         VARCHAR not null
repository_url      TEXT not null
namespace           VARCHAR not null
live_url            TEXT not null
current_status      VARCHAR not null
created_at          TIMESTAMPTZ not null
updated_at          TIMESTAMPTZ not null
```

## deployments

Required logical columns:

``` text
id                  UUID primary key
application_id      UUID foreign key -> applications.id
status              VARCHAR not null
source_revision     VARCHAR nullable
image_tag           TEXT nullable
gitops_commit       VARCHAR nullable
error_code          VARCHAR nullable
error_message       TEXT nullable
created_at          TIMESTAMPTZ not null
updated_at          TIMESTAMPTZ not null
completed_at        TIMESTAMPTZ nullable
```

`image_tag` is NULL for static applications.

Keep `source_revision` and `gitops_commit` separate.

-   `source_revision` = developer source Git commit
-   `image_tag` = container image produced from that source
-   `gitops_commit` = commit containing rendered desired state

Do not store plaintext environment-variable values in normal
application/deployment API response fields.

For MVP implementation, SQLAlchemy 2.x SHOULD be used unless the
existing code strongly favors another lightweight PostgreSQL approach.

A migration tool such as Alembic MAY be used, but it MUST NOT block the
MVP if schema creation is simpler during the hackathon.

------------------------------------------------------------------------

# 15. Image Strategy

FastAPI image naming MUST follow this logical format:

``` text
<registry-host>/rowdyhacks/<app-name>:<short-source-git-sha>
```

Example:

``` text
<registry-host>/rowdyhacks/weather-api:a81f32c
```

Do NOT use `latest`.

The short source SHA SHOULD be 7 characters.

The database MUST retain the source revision separately.

The Kubernetes Deployment MUST reference the generated image tag.

Registry hostname/credentials MUST come from environment/configuration,
not source code.

------------------------------------------------------------------------

# 16. Namespace and URL Naming

For application:

``` text
weather-api
```

Namespace:

``` text
app-weather-api
```

Public hostname:

``` text
weather-api.<PLATFORM_DOMAIN>
```

Live URL:

``` text
https://weather-api.<PLATFORM_DOMAIN>
```

The platform MUST generate these values. Developers cannot override
them.

The public application URL is a hard acceptance criterion.

------------------------------------------------------------------------

# 17. DNS / Traefik Requirement

Because the RowdyHacks environment cannot rely on SSH access for the
demo, public HTTP/HTTPS routing is critical.

The infrastructure MUST provide a DNS strategy capable of resolving
generated application hostnames to Traefik/VKE.

Preferred MVP approach:

-   configure a wildcard DNS record for the platform domain/subdomain
-   point `*.<PLATFORM_DOMAIN>` at the public Traefik load balancer
    address
-   generate one Traefik IngressRoute per application

This prevents the control plane from having to mutate DNS for every
deployment.

The exact DNS provider integration MAY remain outside the control-plane
code, but DNS MUST be configured before the end-to-end demo.

------------------------------------------------------------------------

# 18. Kubernetes Application Defaults

All settings below are platform-owned.

## Common labels

Generated workloads SHOULD include:

``` yaml
app.kubernetes.io/name: <app-name>
app.kubernetes.io/managed-by: rowdyhacks-idp
rowdyhacks.dev/golden-path: <static|fastapi>
```

These labels SHOULD be used by the status/log lookup code.

## Replica count

MVP:

``` text
replicas: 1
```

Developers cannot override it.

## Service

Both Golden Paths SHOULD expose Kubernetes Service port `80`.

Static target port is determined by the selected Nginx runtime.

FastAPI target port:

``` text
8000
```

This allows Traefik routing to consistently target Service port 80.

## Security

Where compatible with the runtime, generated Pods SHOULD use:

-   `runAsNonRoot: true`
-   `allowPrivilegeEscalation: false`
-   dropped Linux capabilities
-   `seccompProfile: RuntimeDefault`

FastAPI Docker images MUST run as a non-root user.

For static hosting, prefer an unprivileged Nginx image/runtime so
non-root execution is practical.

------------------------------------------------------------------------

# 19. Static Manifest Generation

Generated directory:

``` text
apps/static/<app-name>/
```

Required files:

``` text
namespace.yaml
configmap.yaml
deployment.yaml
service.yaml
ingressroute.yaml
kustomization.yaml
```

The ConfigMap contains validated static source content.

The Deployment mounts the ConfigMap content into the Nginx document
root.

The platform SHOULD use deterministic safe ConfigMap keys and
`items[].path` mappings when preserving nested relative paths.

The application MUST be reachable through its generated Traefik
hostname.

No image is built or pushed.

------------------------------------------------------------------------

# 20. FastAPI Manifest Generation

Generated directory:

``` text
idp-gitops-manifests/apps/fastapi/<app-name>/
```

Required files:

``` text
namespace.yaml
deployment.yaml
service.yaml
ingressroute.yaml
kustomization.yaml
```

The MVP MUST NOT render developer secrets or environment-variable values
into these manifests.

The Deployment MUST reference:

``` text
<registry-host>/rowdyhacks/<app-name>:<short-sha>
```

The container listens on `8000`.

The Service exposes port 80 and targets 8000.

The IngressRoute targets Service port 80.

# 21. FastAPI Build Template

The control plane MUST ignore developer Dockerfiles for this Golden
Path.

The platform supplies its own strict Dockerfile template.

Logical build behavior:

1.  use a platform-selected Python Alpine base image
2.  establish a working directory
3.  copy `requirements.txt`
4.  install developer requirements
5.  install/ensure platform runtime dependency Uvicorn
6.  copy application source
7.  create/use a non-root runtime user
8.  expose/use port 8000
9.  run `uvicorn main:app --host 0.0.0.0 --port 8000`

The exact Python Alpine version SHOULD be centralized in platform
configuration/template code rather than accepted from the developer API.

The build uses the Docker SDK on the Debian control-plane VM.

The resulting image MUST be pushed to the private Vultr registry before
GitOps manifests referencing it are committed.

MVP security note: building arbitrary public repositories on the
control-plane VM is not production-grade isolation. Production would use
isolated ephemeral build workers.

------------------------------------------------------------------------

# 22. GitOps Commit Rules

Application generation MUST be deterministic where practical.

A deployment SHOULD produce one logical GitOps commit after all files
are successfully rendered.

Recommended commit format:

``` text
deploy(<app-name>): <short-source-sha>
```

Example:

``` text
deploy(weather-api): a81f32c
```

Deletion:

``` text
delete(<app-name>): remove application
```

Validation/build failures MUST NOT commit partially rendered desired
state.

The deployment record MUST store the resulting GitOps commit SHA after a
successful push.

------------------------------------------------------------------------

# 23. Flux Reconciliation Model

Flux MUST poll the public RowdyHacks GitOps path approximately every 15
seconds.

Infrastructure reconciliation MUST precede application reconciliation.

After the control plane pushes a GitOps commit, it MAY perform a
best-effort Flux reconciliation nudge to reduce demo latency.

Failure to perform the nudge MUST NOT itself fail the deployment if
normal Flux polling can still reconcile.

The control plane MUST then observe Kubernetes until the workload
converges or a deployment timeout is reached.

Git remains the source of truth.

------------------------------------------------------------------------

# 24. Status Polling

The portal will poll the API until deployment reaches a meaningful
terminal/runtime state.

Recommended frontend behavior:

``` text
POST /deploy
     |
     v
receive deployment_id + app_name
     |
     v
GET /apps/{app_name}
     |
     +--> validating -> poll again
     +--> building   -> poll again
     +--> deploying  -> poll again
     +--> running    -> show live URL
     +--> crashing   -> show runtime error/log option
     +--> failed     -> show pipeline error
```

A polling interval around 2--5 seconds is reasonable for the hackathon
UI.

The backend status worker SHOULD poll Kubernetes around every 5 seconds
while deployments are active.

Exact intervals SHOULD be configuration values.

------------------------------------------------------------------------

# 25. Kubernetes Status Mapping

The status code SHOULD use Kubernetes Deployment/Pod state, not merely
the existence of YAML in Git.

`RUNNING`:

-   Deployment exists
-   expected replica is available/ready
-   workload is not in a known failure state

`CRASHING`:

-   workload exists
-   pod/container shows runtime failure such as `CrashLoopBackOff`,
    `ImagePullBackOff`, or `ErrImagePull`
-   or repeated container restarts make the workload unavailable

`DEPLOYING`:

-   GitOps commit has been pushed
-   workload has not yet reached readiness
-   no terminal/runtime failure has been identified

`FAILED`:

-   clone failure
-   Golden Path validation failure
-   Docker build failure
-   registry push failure
-   Git render/commit/push failure
-   Flux/convergence timeout where the workload never successfully
    materializes

Store a useful `error_code` and human-readable `error_message`.

------------------------------------------------------------------------

# 26. Logs Endpoint

Endpoint:

``` text
GET /apps/{app_name}/logs
```

MVP behavior:

-   find the application's current pod using platform labels/namespace
-   return recent container logs
-   default to a small tail such as 100 lines
-   do not implement streaming logs for MVP

A simple response MAY be:

``` json
{
  "app_name": "weather-api",
  "pod": "weather-api-...",
  "lines": [
    "Application startup complete."
  ]
}
```

The endpoint MUST NOT intentionally expose platform secrets.

------------------------------------------------------------------------

# 27. GET /apps

Returns application-level summaries, not deployment internals.

Example:

``` json
[
  {
    "name": "weather-api",
    "golden_path": "fastapi",
    "repository": "https://github.com/example/weather-api",
    "status": "running",
    "live_url": "https://weather-api.example.com",
    "updated_at": "..."
  }
]
```

------------------------------------------------------------------------

# 28. GET /apps/{app_name}

Returns the current application state and enough information for the
frontend deployment screen.

Example shape:

``` json
{
  "name": "weather-api",
  "golden_path": "fastapi",
  "repository": "https://github.com/example/weather-api",
  "namespace": "app-weather-api",
  "status": "running",
  "live_url": "https://weather-api.example.com",
  "latest_deployment": {
    "deployment_id": "dep_...",
    "status": "running",
    "source_revision": "a81f32c...",
    "image_tag": "<registry>/rowdyhacks/weather-api:a81f32c",
    "created_at": "...",
    "completed_at": "..."
  }
}
```

Do not return environment variable values.

------------------------------------------------------------------------

# 29. DELETE /apps/{app_name}

Deletion is GitOps-driven.

The endpoint MUST:

1.  verify application exists
2.  remove its directory under `apps/<golden-path>/<app-name>/`
3.  remove the application from the relevant parent Kustomization
4.  commit/push the deletion
5.  rely on Flux pruning to remove Kubernetes resources
6.  update/remove the application record as appropriate

A `202 Accepted` response is preferred because Kubernetes cleanup is
asynchronous.

Do NOT directly `kubectl delete` application resources as the normal
deletion mechanism.

------------------------------------------------------------------------

# 30. Health Endpoint

Endpoint:

``` text
GET /health
```

Keep it minimal.

Example:

``` json
{
  "status": "ok"
}
```

It MAY later include dependency health, but that is not required to
begin implementation.

`/health` SHOULD remain unauthenticated.

------------------------------------------------------------------------

# 31. Authentication

For the MVP, use HTTP Basic authentication for non-health control-plane
endpoints.

Credentials MUST come from environment variables/secrets.

Do not implement user accounts.

Recommended:

``` text
/health                    unauthenticated
/deploy                    authenticated
/apps*                     authenticated
```

If the portal and API are on different origins, configure CORS from an
explicit environment-configured portal origin. Do not use unrestricted
CORS unless required temporarily during local development.

------------------------------------------------------------------------

# 32. Control-Plane Configuration

Configuration SHOULD be centralized in `app/config.py`.

Expected configuration includes logical values such as:

``` text
DATABASE_URL
PLATFORM_DOMAIN

GITOPS_REPO_URL
GITOPS_BRANCH
GITOPS_TOKEN or equivalent write credential (environment only; never committed)
GITOPS_LOCAL_PATH
GITOPS_MANIFEST_PATH

VULTR_REGISTRY_HOST
VULTR_REGISTRY_USERNAME
VULTR_REGISTRY_PASSWORD

KUBECONFIG or KUBERNETES configuration
FLUX_POLL_INTERVAL
STATUS_POLL_INTERVAL
DEPLOYMENT_TIMEOUT

BASIC_AUTH_USERNAME
BASIC_AUTH_PASSWORD

PORTAL_ORIGIN
```

Names MAY be adjusted to match existing code, but configuration MUST NOT
be hardcoded throughout modules.

Secrets MUST NOT be committed.

------------------------------------------------------------------------

# 33. Control-Plane Module Responsibilities

Preserve the existing module layout where practical.

``` text
app/
├── auth.py
├── builder.py
├── clone.py
├── config.py
├── flux.py
├── gitops.py
├── golden_path.py
├── jobs.py
├── k8s.py
├── main.py
├── models.py
├── overlay.py
├── pipeline.py
└── templates/
```

Recommended responsibilities:

## `main.py`

-   FastAPI app
-   routers/endpoints
-   middleware/CORS
-   dependency wiring
-   startup/shutdown hooks

## `models.py`

-   Pydantic API models
-   deployment status enum
-   response models
-   database models only if existing project structure makes this clean;
    otherwise database models MAY move to a dedicated module

## `config.py`

-   environment-backed settings
-   platform constants

## `golden_path.py`

-   Golden Path definitions
-   repository contract validation
-   static validation
-   FastAPI validation
-   no infrastructure deployment logic

## `clone.py`

-   safe temporary clone
-   public GitHub/default branch behavior
-   source commit SHA discovery
-   cleanup

## `builder.py`

-   FastAPI Docker build
-   platform Dockerfile injection/template use
-   image tagging
-   registry push

Static deployments MUST bypass this module's image build path.

## `gitops.py`

-   clone/update private runtime GitOps repo
-   render/write application desired state
-   update parent Kustomization
-   commit/push
-   delete app desired state
-   return GitOps commit SHA

## `overlay.py`

-   manifest rendering helpers if useful
-   SHOULD NOT create a competing architecture to `gitops.py`

## `flux.py`

-   optional/best-effort Flux reconciliation nudge
-   Flux status helpers if required

## `k8s.py`

-   Kubernetes status
-   pod lookup
-   logs
-   runtime health mapping
-   MUST NOT be the normal application deployment writer

## `pipeline.py`

-   orchestrates deployment lifecycle
-   transitions deployment states
-   calls clone -\> validation -\> optional build -\> GitOps -\> Flux
    -\> convergence

## `jobs.py`

-   lightweight background execution/status polling
-   do not add Celery/external queue for MVP

## `auth.py`

-   HTTP Basic authentication

## `agents.py`

Not part of the MVP critical path. Do not spend implementation time here
unless all core functionality works.

------------------------------------------------------------------------

# 34. Pipeline --- Static

Canonical sequence:

``` text
POST /deploy
      |
      v
request validation
      |
      v
create/find application
create deployment
      |
      v
202 Accepted
      |
      v
PENDING -> VALIDATING
      |
      v
clone public GitHub repo
      |
      v
validate static Golden Path
      |
      v
capture source commit SHA
      |
      v
render ConfigMap + K8s manifests
      |
      v
write apps/static/<name>/
update parent kustomization
      |
      v
Git commit + push
      |
      v
DEPLOYING
      |
      v
best-effort Flux reconcile
      |
      v
poll VKE
      |
      +--> ready -> RUNNING
      |
      +--> timeout/pipeline error -> FAILED
      |
      +--> workload runtime failure -> CRASHING
```

------------------------------------------------------------------------

# 35. Pipeline --- FastAPI

Canonical sequence:

``` text
POST /deploy
      |
      v
request validation
      |
      v
create/find application
create deployment
      |
      v
202 Accepted
      |
      v
PENDING -> VALIDATING
      |
      v
clone public GitHub repo
      |
      v
validate FastAPI Golden Path
      |
      v
capture source commit SHA
      |
      v
BUILDING
      |
      v
inject platform Dockerfile
Docker SDK build
      |
      v
tag:
registry/rowdyhacks/<name>:<short-sha>
      |
      v
push Vultr registry
      |
      v
render Kubernetes desired state
      |
      v
Git commit + push
      |
      v
DEPLOYING
      |
      v
best-effort Flux reconcile
      |
      v
poll VKE
      |
      +--> ready -> RUNNING
      |
      +--> pipeline/convergence error -> FAILED
      |
      +--> runtime failure -> CRASHING
```

------------------------------------------------------------------------

# 36. Error Codes

Keep error handling small but structured.

Recommended MVP codes:

``` text
INVALID_REPOSITORY
CLONE_FAILED
GOLDEN_PATH_VIOLATION
STATIC_SITE_TOO_LARGE
BUILD_FAILED
REGISTRY_PUSH_FAILED
GITOPS_FAILED
FLUX_TIMEOUT
DEPLOYMENT_TIMEOUT
RUNTIME_CRASH
APP_NOT_FOUND
```

The frontend should display `error_message` in human-readable form.

Do not expose credentials or raw secret-bearing subprocess output.

------------------------------------------------------------------------

# 37. Retry Behavior

MVP retry policy:

-   Do not build a sophisticated automatic retry framework.
-   A new `POST /deploy` for the same application is the manual
    retry/redeploy mechanism.
-   Flux itself naturally retries reconciliation.
-   A failed best-effort Flux nudge does not immediately fail the
    deployment.
-   Docker build/push/Git failures MAY be attempted once and then marked
    failed.

Prefer deterministic behavior over hidden retry loops during the
hackathon.

------------------------------------------------------------------------

# 38. Frontend Integration Contract

The portal is developed independently and SHOULD use a service
abstraction so mock data can later be replaced with the real API.

Logical frontend functions:

``` text
getApps()
getApp(name)
deployApp(payload)
getLogs(name)
deleteApp(name)
```

The frontend MUST understand:

``` text
pending
validating
building
deploying
running
crashing
failed
```

Static applications skip `building`.

The frontend SHOULD poll `GET /apps/{app_name}` while the application is
in an in-progress state.

When `running`, it SHOULD prominently expose the live application URL.

When `failed`, it SHOULD show the platform error message.

When `crashing`, it SHOULD make runtime logs easy to inspect.

The frontend MUST NOT contain Docker, Kubernetes, Flux, or GitOps
orchestration logic.

------------------------------------------------------------------------

# 39. Build Order

Build vertically. Do not attempt to complete every module before testing
the system.

## Phase 0 --- Vultr infrastructure

1.  finish/validate Terraform Stage 1
2.  provision control-plane VM
3.  provision VKE
4.  provision private Vultr registry
5.  configure firewall
6.  obtain/test VKE kubeconfig
7.  configure platform DNS/wildcard strategy
8.  bootstrap Flux + Traefik through Stage 2
9.  create/connect public RowdyHacks repository under
    `idp-gitops-manifests/`

## Phase 1 --- API contract

Implement:

-   Pydantic request models
-   status enum
-   `/health`
-   `POST /deploy`
-   `GET /apps`
-   `GET /apps/{app_name}`
-   initial background job mechanism

## Phase 2 --- PostgreSQL

Implement:

-   `applications`
-   `deployments`
-   persistence for state transitions
-   latest deployment lookup

## Phase 3 --- clone + validation

Implement:

-   safe public GitHub clone
-   default branch only
-   source SHA
-   static Golden Path validator
-   FastAPI Golden Path validator

## Phase 4 --- static end-to-end FIRST

Implement:

-   static ConfigMap generation
-   Namespace
-   Deployment
-   Service
-   IngressRoute
-   Kustomization
-   Git commit/push
-   Flux reconciliation
-   Kubernetes status polling

Do not proceed until a trivial `index.html` repository becomes publicly
reachable at:

``` text
https://<app-name>.<PLATFORM_DOMAIN>
```

This is the first major acceptance milestone.

## Phase 5 --- FastAPI build path

Implement:

-   platform Dockerfile
-   Docker SDK
-   image tag from short source SHA
-   Vultr registry push
-   FastAPI Kubernetes manifests
-   end-to-end deployment

## Phase 6 --- operational endpoints

Implement:

-   logs
-   delete
-   runtime crash mapping
-   deployment errors

## Phase 7 --- security/UI integration

Implement:

-   HTTP Basic auth
-   CORS
-   frontend real API adapter
-   error presentation
-   demo polish

------------------------------------------------------------------------

# 40. Acceptance Criteria

The MVP is complete when all MUST criteria below work.

## Infrastructure

-   Terraform provisions the required Vultr infrastructure.
-   VKE is reachable from the control-plane tooling.
-   Flux reconciles the public RowdyHacks GitOps path.
-   Traefik provides public routing.
-   wildcard/generated application DNS works.

## Static Golden Path

Given a compliant public GitHub static repository:

-   `POST /deploy` returns 202 quickly
-   deployment transitions through validation/deployment states
-   manifests are committed to Git
-   Flux applies them
-   application becomes `running`
-   generated HTTPS/public URL works from a judge's browser
-   developer supplied no Dockerfile or Kubernetes YAML

## FastAPI Golden Path

Given a compliant public FastAPI repository:

-   `POST /deploy` returns 202 quickly
-   source is validated
-   platform builds its own Docker image
-   image is tagged with short source SHA
-   image is pushed to private Vultr registry
-   desired state is committed to Git
-   Flux deploys it
-   application becomes `running`
-   generated public URL works
-   developer supplied no Dockerfile or Kubernetes YAML

## Failure behavior

-   invalid API requests return validation errors
-   noncompliant repositories become `failed`
-   build/push/GitOps failures become `failed`
-   Kubernetes runtime failures can be represented as `crashing`
-   frontend can retrieve useful status/error information

## GitOps

-   application desired state is visible/auditable by judges in the
    public GitHub repository
-   normal application creation/deletion is Git-driven
-   Flux pruning removes deleted application resources
-   control plane does not mutate `clusters/**` or `infrastructure/**`
    during normal application deployment

------------------------------------------------------------------------

# 41. Demo Story

The strongest demo path is intentionally simple:

1.  show a tiny public GitHub repository
2.  show that it contains no Dockerfile and no Kubernetes YAML
3.  paste/select the repository in the developer portal
4.  choose `static` or `fastapi`
5.  click Deploy
6.  show progress:
    -   Validating
    -   Building (FastAPI only)
    -   Deploying
    -   Running
7.  briefly show the generated GitOps commit
8.  click the generated live URL
9.  show the application running publicly on VKE

The technical message:

> Developers declare application intent. The platform standardizes the
> infrastructure path.

------------------------------------------------------------------------

# 42. Future Work

Explicitly document, but do not implement unless core MVP is complete:

-   SOPS/age encrypted GitOps secrets
-   External Secrets Operator
-   isolated/ephemeral build workers
-   GitHub OAuth/private source repositories
-   webhook-based automatic deployments
-   per-team RBAC
-   deployment history UI
-   rollback endpoint backed by Git
-   custom domains
-   multiple environments
-   staging/production promotion
-   autoscaling
-   policy enforcement
-   vulnerability scanning
-   observability stack
-   OpenTelemetry
-   additional Golden Paths
-   managed database provisioning
-   Backstage-style software catalog
-   AI platform assistant

------------------------------------------------------------------------

# 43. Instructions to Claude

When implementing from this document:

1.  **Do not redesign the architecture.**
2.  Preserve existing working code where it matches this specification.
3.  Prefer small changes over rewrites.
4.  Implement one phase at a time.
5.  Do not introduce additional infrastructure dependencies without a
    clear requirement.
6.  Keep the developer-facing API intentionally tiny.
7.  Do not expose infrastructure knobs through `/deploy`.
8.  Treat the public RowdyHacks GitOps path as the Kubernetes source of
    truth.
9.  Do not deploy application resources directly through the Kubernetes
    API during the normal deployment path.
10. Use Kubernetes access only for observation/logs and optional Flux
    reconciliation assistance.
11. Make static deployment work end-to-end before adding complexity to
    the FastAPI build path.
12. Treat the public URL as a core acceptance criterion.
13. If existing code conflicts with this document, explain the conflict
    before changing architecture.
14. Ask for missing credentials/domain-specific values rather than
    inventing them.
15. Do not spend time on `agents.py` or optional AI functionality until
    the core platform works.

------------------------------------------------------------------------

# 44. Final MVP Boundary

The platform is successful if it can reliably demonstrate:

``` text
PUBLIC GITHUB REPO
        |
        v
TINY DEVELOPER INTENT
        |
        v
IDP CONTROL PLANE
        |
        +--> validate
        +--> package
        +--> build/push when required
        +--> generate desired state
        |
        v
GIT
        |
        v
FLUX
        |
        v
VKE
        |
        v
TRAEFIK
        |
        v
PUBLIC LIVE URL
```

That is the MVP. Build this first.
