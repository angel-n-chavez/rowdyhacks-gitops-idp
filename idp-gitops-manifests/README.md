# idp-gitops-manifests

The GitOps **state repo** for the mini-IDP. Flux watches this repo; the control
plane writes into it. Nothing here is edited by hand once the platform runs
(except `apps-base/`, which changes almost never).

```
clusters/homelab-idp/
  flux-system/        <- created by `flux bootstrap` (do not hand-edit, except intervals)
  apps.yaml           <- Flux Kustomization: watch ./apps-prod, interval 15s, prune: true
apps-base/
  web-service/        <- Golden Path #1 (FastAPI on 8080, TCP probes)
  static-site/        <- Golden Path #2 (nginx on 8080, HTTP probes, tiny resources)
apps-prod/
  _platform/          <- seed so the dir is never empty (underscore can't clash with an app name)
  <app>/kustomization.yaml   <- written by the control plane, one small file per app
examples/payment-api/ <- hand-written overlay for smoke-testing Flux + Traefik with no control plane
scripts/verify.sh     <- offline kustomize checks (no cluster needed)
```

## The contract
Every base resource is literally named `app` (selector `app: app`) and the
overlay supplies only: `namespace`, image name+tag, labels, env vars (via
`configMapGenerator`), and the ingress host. The base is never patched beyond
that, so the part that varies is tiny and uniform.

## Verify offline
```bash
./scripts/verify.sh        # needs kustomize or kubectl; no cluster
```

## Use it
See `HOMELAB-DRYRUN.md` in the `idp-control-plane` zip for the full walkthrough.
Short version: push this to GitHub (private), then
```bash
export GITHUB_TOKEN=<fine-grained PAT: Administration RW + Contents RW on THIS repo>
flux bootstrap github --owner=<you> --repository=idp-gitops-manifests \
  --branch=main --path=clusters/homelab-idp --personal
git pull   # then edit clusters/homelab-idp/flux-system/gotk-sync.yaml:
           #   GitRepository.spec.interval: 15s   and   Kustomization.spec.interval: 15s
```
