(() => {
  const apiUrl = new URLSearchParams(window.location.search).get("api") || "http://localhost:8000";
  const API_BASE_URL = new URL(apiUrl).origin;
  const activeStatuses = new Set(["PENDING", "VALIDATING", "BUILDING", "DEPLOYING"]);
  const statusLabels = {
    PENDING: "Queued",
    VALIDATING: "Validating",
    BUILDING: "Building",
    DEPLOYING: "Deploying",
    RUNNING: "Running",
    CRASHING: "Crashing",
    FAILED: "Failed",
  };

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        ...options,
        headers: { Accept: "application/json", ...options.headers },
      });
    } catch {
      throw new Error("Can't reach the control plane at http://localhost:8000. Check that it's running and try again.");
    }

    if (!response.ok) {
      let message = `The control plane returned HTTP ${response.status}.`;
      try {
        const body = await response.json();
        if (body.message) message = body.message;
        else if (body.detail?.length) message = body.detail.map((item) => item.msg).join(" ");
      } catch {
        // Keep the HTTP status message when the server did not return JSON.
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }

    return response.status === 204 ? null : response.json();
  }

  function toPortalApp(app) {
    const status = String(app.status).toUpperCase();
    const latest = app.latest_deployment;
    const updatedAt = new Date(app.updated_at);
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - updatedAt.getTime()) / 1000));
    const updated = Number.isNaN(updatedAt.getTime()) ? app.updated_at
      : elapsedSeconds < 60 ? "Just now"
        : elapsedSeconds < 3600 ? `${Math.floor(elapsedSeconds / 60)} min ago`
          : elapsedSeconds < 86400 ? `${Math.floor(elapsedSeconds / 3600)} hr ago`
            : `${Math.floor(elapsedSeconds / 86400)} day${elapsedSeconds >= 172800 ? "s" : ""} ago`;
    const type = app.golden_path === "fastapi" ? "FastAPI" : "Static Website";

    return {
      name: app.name,
      type,
      repository: app.repository,
      status,
      url: ["RUNNING", "CRASHING"].includes(status) ? app.live_url : null,
      updated,
      deployment: latest?.deployment_id || "—",
      summary: `${type} from ${app.repository.replace(/\/$/, "").split("/").pop()}.`,
      issue: latest?.error_message || (latest?.error_code === "PIPELINE_NOT_IMPLEMENTED"
        ? "The control-plane deployment pipeline is not implemented yet."
        : null),
      errorCode: latest?.error_code || null,
      latestDeployment: latest,
    };
  }

  async function getApps() {
    const apps = await request("/apps");
    return apps.map(toPortalApp);
  }

  async function getApp(name) {
    try {
      return toPortalApp(await request(`/apps/${encodeURIComponent(name)}`));
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  }

  async function deployApp(payload) {
    const goldenPath = payload.goldenPath === "FastAPI" || payload.goldenPath === "fastapi"
      ? "fastapi"
      : "static";
    await request("/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: payload.name,
        repository: payload.repository,
        golden_path: goldenPath,
      }),
    });
    const app = await getApp(payload.name);
    if (!app) throw new Error("The deployment was accepted, but the application was not returned by the control plane.");
    return app;
  }

  window.ControlPlaneService = {
    getApps,
    getApp,
    deployApp,
    supportsLogs: false,
    supportsDelete: false,
  };
})();
