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

## Deliverables

* Screen designs and navigation flow.
* Reusable components and status indicators.
* Deploy form for both Golden Paths.
* Responsive layout.
* Recommended UI fields and interactions.

The backend API contract is being designed separately. Do not assume that a UI action is already supported by the API; identify proposed interactions for confirmation before finalizing them.
