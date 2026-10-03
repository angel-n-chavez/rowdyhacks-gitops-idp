(() => {
  const apps = new Map([
    ["my-portfolio", {
      name: "my-portfolio",
      type: "Static Website",
      repository: "https://github.com/jordandavis/my-portfolio",
      status: "RUNNING",
      url: "https://my-portfolio.apps.rowdyhacks.dev",
      updated: "4 min ago",
      deployment: "#deploy-1042",
      summary: "Your personal site, ready for the world.",
    }],
    ["weather-api", {
      name: "weather-api",
      type: "FastAPI",
      repository: "https://github.com/jordandavis/weather-api",
      status: "BUILDING",
      url: null,
      updated: "Just now",
      deployment: "#deploy-1048",
      summary: "A small weather service for your next project.",
    }],
    ["payment-api", {
      name: "payment-api",
      type: "FastAPI",
      repository: "https://github.com/jordandavis/payment-api",
      status: "CRASHING",
      url: "https://payment-api.apps.rowdyhacks.dev",
      updated: "12 min ago",
      deployment: "#deploy-1046",
      summary: "Payment service for the storefront experience.",
      issue: "The application stopped responding after its latest deployment.",
    }],
    ["docs-site", {
      name: "docs-site",
      type: "Static Website",
      repository: "https://github.com/jordandavis/docs-site",
      status: "FAILED",
      url: null,
      updated: "Yesterday",
      deployment: "#deploy-1031",
      summary: "Team documentation and project guides.",
      issue: "We couldn't complete this deployment. Check the repository and try again.",
    }],
  ]);

  const pause = (milliseconds = 180) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const copy = (app) => app ? { ...app } : null;

  async function getApps() {
    await pause(240);
    return Array.from(apps.values(), copy).sort((left, right) => left.name.localeCompare(right.name));
  }

  async function getApp(name) {
    await pause(140);
    return copy(apps.get(name));
  }

  async function deployApp(payload) {
    await pause(280);
    const app = {
      name: payload.name,
      type: payload.goldenPath,
      repository: payload.repository,
      status: "BUILDING",
      url: null,
      updated: "Just now",
      deployment: `#deploy-${Math.floor(1050 + Math.random() * 800)}`,
      summary: payload.goldenPath === "Static Website" ? "Static website deployment." : "FastAPI web service deployment.",
    };
    apps.set(app.name, app);

    setTimeout(() => {
      const current = apps.get(app.name);
      if (!current || current.deployment !== app.deployment) return;
      current.status = "DEPLOYING";
      current.updated = "Just now";
    }, 2600);
    setTimeout(() => {
      const current = apps.get(app.name);
      if (!current || current.deployment !== app.deployment) return;
      current.status = "RUNNING";
      current.url = `https://${app.name}.apps.rowdyhacks.dev`;
      current.updated = "Just now";
    }, 6500);
    return copy(app);
  }

  async function getLogs(name) {
    await pause(160);
    const app = apps.get(name);
    if (!app) return [];
    const lines = [
      `[portal] Opening deployment ${app.deployment}`,
      `[portal] Golden Path: ${app.type}`,
      `[portal] Repository: ${app.repository}`,
    ];
    if (app.status === "FAILED") lines.push("[portal] Deployment failed. Review your repository and try again.");
    else if (app.status === "CRASHING") lines.push("[portal] Application health check did not respond.");
    else lines.push(`[portal] Current status: ${app.status.toLowerCase()}`);
    return lines;
  }

  async function deleteApp(name) {
    await pause(180);
    return apps.delete(name);
  }

  window.MockService = { getApps, getApp, deployApp, getLogs, deleteApp };
})();