# RowdyHacks IDP: Developer Portal UI/UX Brief

## Product vision

Design a developer portal for a lightweight Internal Developer Platform. Developers submit a public GitHub repository and select one of two supported Golden Paths. The platform handles packaging, deployment, routing, and Kubernetes configuration.

The experience should feel like a simplified internal Heroku or Render dashboard, but designed for an engineering hackathon demo.

## Required screens

1. **Dashboard:** List deployed applications, their type, deployment status, and live URL. Include a prominent Deploy Application action.
2. **Deploy Application:** Collect application name, public GitHub repository URL, and Golden Path selection:

   * Static Website
   * FastAPI Web Service
3. **Application Details:** Show application name, type, repository, current status, live URL, and deployment information.
4. **Deployment Feedback:** Show progress, success, and failure states. Distinguish building from deploying and running.
5. **Optional Operations:** Provide controls for viewing logs, redeploying, and deleting an application.

## Design constraints

* Developers should not need to understand Docker, Kubernetes, Flux, or YAML.
* Use clear status labels: Building, Deploying, Running, Crashing, and Failed.
* Include loading, empty, validation-error, and API-error states.
* Make the live URL easy to find and open.
* Design for a live hackathon demonstration: fast to understand, visually clear, and technically credible.

## Run locally

Serve the portal from the repository root (the control plane only allows these local origins):

```bash
cd portal
python3 -m http.server 5173
```

Open http://localhost:5173/ for the mock demo. To use the local control plane, open
http://localhost:5173/?api after starting it using the steps in
[`idp-control-plane/README.md`](../idp-control-plane/README.md). The API mode
loads real applications and supports deploy, redeploy, and status polling.
If the control plane uses a different origin, pass it as the `api` value, for
example `http://localhost:5173/?api=http%3A%2F%2Flocalhost%3A8001`.
Logs and delete remain available only in mock mode until the control plane
implements those endpoints. Use `http://localhost:5173/` to return to mock mode.

## Mock service

`mock-service.js` provides `getApps()`, `getApp(name)`, `deployApp(payload)`, `getLogs(name)`, and `deleteApp(name)`. Its in-memory demo data covers BUILDING, DEPLOYING, RUNNING, CRASHING, and FAILED. New mock deployments advance through BUILDING, DEPLOYING, and RUNNING, then receive a demo live URL. Reloading the page resets the demo data.

The UI depends on a small service boundary; it does not contain deployment or infrastructure logic. `api-service.js` adapts the control-plane API contract for the existing UI.

## Useful platform fields

The portal currently displays the application name, Golden Path, repository, status, deployment reference, last-updated label, live URL, a short failure explanation, and recent logs. The control-plane API currently provides these fields, including deployment status and failure details. The portal displays live URLs only for running or crashing apps.
