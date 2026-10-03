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

Open `index.html` in a browser. The portal is static and does not need the FastAPI service or a local build step.

## Mock service

`mock-service.js` provides `getApps()`, `getApp(name)`, `deployApp(payload)`, `getLogs(name)`, and `deleteApp(name)`. Its in-memory demo data covers BUILDING, DEPLOYING, RUNNING, CRASHING, and FAILED. New mock deployments advance through BUILDING, DEPLOYING, and RUNNING, then receive a demo live URL. Reloading the page resets the demo data.

The UI depends only on this small service boundary; it does not contain deployment or infrastructure logic, and it assumes no real endpoint or response format.

## Useful platform fields

The portal currently displays the application name, Golden Path, repository, status, deployment reference, last-updated label, live URL, a short failure explanation, and recent logs. A future API contract should provide user-facing status and failure details plus a URL when one is available. The portal can continue to own the presentation and navigation around those values.
